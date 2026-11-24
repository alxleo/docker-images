"""Exercise installed subscription snapshot state without network or model calls."""

import asyncio
import os
from contextlib import nullcontext
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

os.environ['LITELLM_LOCAL_MODEL_COST_MAP'] = 'True'

import anyio
from litellm.proxy._experimental.mcp_server import subscriptions
from litellm.proxy._experimental.mcp_server.contracts import OperationContext
from litellm.proxy._types import UserAPIKeyAuth
from litellm.types.mcp_server.mcp_server_manager import MCPServer
from mcp.server.context import ServerRequestContext
from mcp.server.session import ServerSession
from mcp.shared.subscriptions import ToolsListChanged, event_to_notification
from mcp.types import (
    PromptsCapability,
    ResourcesCapability,
    ServerCapabilities,
    SubscriptionFilter,
    SubscriptionsAcknowledgedNotification,
    SubscriptionsListenRequestParams,
    ToolsCapability,
)


class CatalogSession:
    protocol_version = '2025-11-25'
    server_capabilities = ServerCapabilities(tools=ToolsCapability.model_validate({'listChanged': True}))


class InProcessCatalog:
    """Deliver a capability-bearing session to the subscription state machine."""

    def __init__(self):
        self.receive = None

    async def run_with_session(self, operation, *, on_notification):
        self.receive = on_notification
        await operation(CatalogSession())


async def parallel_setup(*, legacy=True, fail_snapshot=False):
    connection_gate = asyncio.Barrier(3)
    catalog_gate = asyncio.Barrier(3)
    reads = 0
    active = 0
    checks = 0
    current = 'before-connections'
    sent = []
    acknowledged = asyncio.Event()
    changed = asyncio.Event()
    expected_reads = 3 if legacy else 6

    class CompleteSession(CatalogSession):
        server_capabilities = ServerCapabilities(
            tools=ToolsCapability.model_validate({'listChanged': True}),
            prompts=PromptsCapability.model_validate({'listChanged': True}),
            resources=ResourcesCapability.model_validate({'listChanged': True}),
        )

    class GatedCatalog(InProcessCatalog):
        async def run_with_session(self, operation, *, on_notification):
            nonlocal active
            self.receive = on_notification
            active += 1
            try:
                await connection_gate.wait()
                await operation(CompleteSession())
            finally:
                active -= 1

    targets = tuple(
        subscriptions.SubscriptionTarget(
            MCPServer(server_id=f'parallel-{n}', name=f'parallel-{n}', transport='http'),
            GatedCatalog(), f'credential-{n}',
        )
        for n in range(3)
    )
    context = OperationContext(
        _caller=UserAPIKeyAuth(user_id='parallel'),
        mcp_servers=tuple(target.server.server_id for target in targets),
    )

    async def authorize():
        nonlocal checks, current
        checks += 1
        if checks == 2:
            current = 'after-connections'
        return context

    async def resolve(observed_context):
        assert observed_context is context
        return targets

    async def fingerprint(event, observed_context):
        nonlocal reads
        assert observed_context is context
        reads += 1
        assert reads <= expected_reads, 'Concurrent listeners repeated the shared catalog batch'
        await catalog_gate.wait()
        if fail_snapshot:
            raise ValueError('Isolated catalog failure')
        return current + type(event).__name__

    async def send(notification, related_request_id=None, **_kwargs):
        assert legacy or related_request_id == 'modern-listener'
        if isinstance(notification, SubscriptionsAcknowledgedNotification):
            acknowledged.set()
        else:
            sent.append(notification.method)
            changed.set()

    owner = subscriptions.GatewaySubscriptions(resolve_targets=resolve)
    # The in-process sink implements the session operations exercised here.
    sink = cast(ServerSession, SimpleNamespace(client_params=object(), send_notification=send))
    ctx = ServerRequestContext(
        session=sink,
        lifespan_context=None, protocol_version='2025-11-25' if legacy else '2026-07-28',
        method='notifications/initialized' if legacy else 'subscriptions/listen',
        request_id=None if legacy else 'modern-listener',
    )
    authorization = subscriptions.SubscriptionAuthorization(context, authorize, lambda auth, *_: auth.user_id)
    failed = False
    try:
        with patch.object(subscriptions, '_listing', fingerprint):
            initializing = owner.initializing(ctx) if legacy else nullcontext()
            async with anyio.create_task_group() as group, initializing:
                if legacy:
                    group.start_soon(owner.legacy_session, ctx, authorization)
                else:
                    params = SubscriptionsListenRequestParams(notifications=SubscriptionFilter.model_validate({
                        'toolsListChanged': True, 'promptsListChanged': True, 'resourcesListChanged': True,
                    }))
                    group.start_soon(owner.listen, ctx, params, authorization, authorization.owner)
                with anyio.fail_after(12):
                    if legacy:
                        await owner.wait_initialized(ctx)
                    else:
                        await acknowledged.wait()
                        while len(sent) < 3:
                            changed.clear()
                            await changed.wait()
                if not fail_snapshot:
                    assert reads == expected_reads and active == 3
                    assert len(sent) == (0 if legacy else 3), sent
                group.cancel_scope.cancel()
    except* ValueError:
        if not fail_snapshot:
            raise
        failed = True
    assert failed == fail_snapshot
    assert reads == (3 if fail_snapshot else expected_reads)
    assert active == 0


async def main():
    await parallel_setup()
    await parallel_setup(fail_snapshot=True)
    await parallel_setup(legacy=False)
    await parallel_setup(legacy=False, fail_snapshot=True)
    targets = tuple(
        subscriptions.SubscriptionTarget(
            MCPServer(server_id=f'catalog-{n}', name=f'catalog-{n}', transport='http'),
            InProcessCatalog(), f'credential-{n}',
        )
        for n in range(3)
    )

    async def resolve(_context):
        return targets

    owner = subscriptions.GatewaySubscriptions(resolve_targets=resolve)

    async def exercise(caller, transitions):
        current = 'initial-' + caller
        checks = 0
        allowance = 1
        sent = []
        snapshots = []
        changed = asyncio.Event()
        context = OperationContext(
            _caller=UserAPIKeyAuth(user_id=caller),
            mcp_servers=tuple(target.server.server_id for target in targets),
        )

        async def authorize():
            nonlocal checks, current
            checks += 1
            if checks in transitions:
                current = transitions[checks]
            return context

        async def fingerprint(_event, observed_context):
            nonlocal allowance
            assert observed_context.user_api_key_auth.user_id == caller
            allowance -= 1
            if allowance < 0:
                raise AssertionError('Subscription setup exhausted its isolated metadata allowance')
            assert observed_context.mcp_servers == context.mcp_servers
            snapshots.append(current)
            return current

        async def send(notification, **_kwargs):
            sent.append(notification.method)
            changed.set()

        sink = cast(ServerSession, SimpleNamespace(client_params=object(), send_notification=send))
        ctx = ServerRequestContext(
            session=sink, lifespan_context=None, protocol_version='2025-11-25',
            method='notifications/initialized', request_id=None,
        )
        authorization = subscriptions.SubscriptionAuthorization(
            context, authorize, lambda auth, *_: auth.user_id,
        )
        with patch.object(subscriptions, '_listing', fingerprint):
            async with anyio.create_task_group() as group, owner.initializing(ctx):
                group.start_soon(owner.legacy_session, ctx, authorization)
                with anyio.fail_after(3):
                    await owner.wait_initialized(ctx)
                for _ in range(4):
                    await asyncio.sleep(0)
                assert sent == [], sent
                assert snapshots[-1] == current
                allowance = 1
                current = 'live-change-' + caller
                changed.clear()
                await targets[0].client.receive(event_to_notification(ToolsListChanged(), {}))
                with anyio.fail_after(3):
                    await changed.wait()
                assert len(sent) == 1, sent
                group.cancel_scope.cancel()

    await exercise('alice', {2: 'after-first-connect', 3: 'after-second-connect'})
    await exercise('bob', {})
    print('Constant setup metadata work preserves final changes, live updates and full caller scope')


asyncio.run(main())
