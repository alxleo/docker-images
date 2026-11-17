"""Exercise installed subscription snapshot state without network or model calls."""

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import patch

os.environ['LITELLM_LOCAL_MODEL_COST_MAP'] = 'True'

import anyio
from litellm.proxy._experimental.mcp_server import subscriptions
from litellm.proxy._experimental.mcp_server.contracts import OperationContext
from litellm.proxy._types import UserAPIKeyAuth
from litellm.types.mcp_server.mcp_server_manager import MCPServer
from mcp.server.context import ServerRequestContext
from mcp.shared.subscriptions import ToolsListChanged, event_to_notification
from mcp.types import (
    PromptsCapability,
    ResourcesCapability,
    ServerCapabilities,
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


async def parallel_setup():
    connection_gate = asyncio.Barrier(3)
    catalog_gate = asyncio.Barrier(3)
    reads = 0
    active = 0

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
        return context

    async def resolve(observed_context):
        assert observed_context is context
        return targets

    async def fingerprint(event, observed_context):
        nonlocal reads
        assert observed_context is context
        reads += 1
        assert reads <= 6, 'Concurrent listeners repeated the shared catalog batch'
        await catalog_gate.wait()
        return type(event).__name__

    async def send(_notification, **_kwargs):
        raise AssertionError('Unchanged catalogs must not emit a setup notification')

    owner = subscriptions.GatewaySubscriptions(resolve_targets=resolve)
    ctx = ServerRequestContext(
        session=SimpleNamespace(client_params=object(), send_notification=send),
        lifespan_context=None, protocol_version='2025-11-25',
        method='notifications/initialized', request_id=None,
    )
    authorization = subscriptions.SubscriptionAuthorization(context, authorize, lambda auth, *_: auth.user_id)
    with patch.object(subscriptions, '_listing', fingerprint):
        async with anyio.create_task_group() as group, owner.initializing(ctx):
            group.start_soon(owner.legacy_session, ctx, authorization)
            with anyio.fail_after(3):
                await owner.wait_initialized(ctx)
            assert reads == 6 and active == 3
            group.cancel_scope.cancel()
    assert active == 0


async def main():
    await parallel_setup()
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
        allowance = 4
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

        sink = SimpleNamespace(client_params=object(), send_notification=send)
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
                assert sent == ['notifications/tools/list_changed'] * bool(transitions), sent
                assert snapshots[-1] == current
                allowance = 1
                current = 'live-change-' + caller
                changed.clear()
                await targets[0].client.receive(event_to_notification(ToolsListChanged(), {}))
                with anyio.fail_after(3):
                    await changed.wait()
                assert len(sent) == bool(transitions) + 1, sent
                group.cancel_scope.cancel()

    await exercise('alice', {2: 'after-first-connect', 3: 'after-second-connect'})
    await exercise('bob', {})
    print('Constant setup metadata work preserves final changes, live updates and full caller scope')


asyncio.run(main())
