# Dockerfile structural policies.
#
# Enforces invariants that hadolint cannot express:
# - USER must exist in the final stage (not root)
# - EXPOSE implies HEALTHCHECK must exist in the same stage
#
# Exemptions via comments in the Dockerfile:
#   # conftest:exempt=user_required -- reason
#   # conftest:exempt=healthcheck_required -- reason
#
# Run: conftest test --parser dockerfile -p policy/ */Dockerfile mcp/Dockerfile.*
package main

import rego.v1

# Guard: only fire on Dockerfile input (array of {Cmd, Value, Stage} objects).
# When conftest loads all .rego files from policy/, compose YAML input would
# otherwise trigger Dockerfile rules (e.g., "no USER found" on empty set).
_is_dockerfile if {
	some i
	input[i].Cmd
}

# Find the highest stage number (final stage)
final_stage := max({input[i].Stage | some i})

# Collect instructions in the final stage
final_stage_cmds contains lower(input[i].Cmd) if {
	input[i].Stage == final_stage
}

# Find the last USER value in the final stage
last_user_index := max({i | some i; input[i].Stage == final_stage; lower(input[i].Cmd) == "user"})

last_user := input[last_user_index].Value[0] if {
	last_user_index != null
}

# Collect exemption comments from anywhere in the Dockerfile
exemptions contains rule if {
	some i
	lower(input[i].Cmd) == "comment"
	some val in input[i].Value
	contains(val, "conftest:exempt=")
	rule := trim_space(split(split(val, "conftest:exempt=")[1], " ")[0])
}

# Check: final stage must have a non-root USER
deny contains msg if {
	_is_dockerfile
	not "user" in final_stage_cmds
	not "user_required" in exemptions
	msg := "Dockerfile must have a USER directive in the final stage. Add USER 1000 before ENTRYPOINT."
}

deny contains msg if {
	_is_dockerfile
	last_user in {"root", "0"}
	not "user_required" in exemptions
	msg := sprintf("Final USER should not be root (found: %s). Use a non-root UID.", [last_user])
}

# Check: EXPOSE implies HEALTHCHECK in the same stage
deny contains msg if {
	_is_dockerfile
	"expose" in final_stage_cmds
	not "healthcheck" in final_stage_cmds
	not "healthcheck_required" in exemptions
	msg := "Dockerfile has EXPOSE but no HEALTHCHECK. Add a HEALTHCHECK directive."
}

# Check: COPY/ADD must not target /root/ in the final stage.
# /root/ is mode 700 — inaccessible to non-root USER (UID 1000).
# Build stages are exempt (only exist during build, always run as root).
deny contains msg if {
	_is_dockerfile
	input[i].Stage == final_stage
	cmd := lower(input[i].Cmd)
	cmd in {"copy", "add"}
	dest := input[i].Value[count(input[i].Value) - 1]
	startswith(dest, "/root")
	not "no_root_paths" in exemptions
	msg := sprintf(
		"%s destination %s is under /root/ — inaccessible to non-root USER. Use /app/ or /usr/local/bin/ instead.",
		[upper(cmd), dest],
	)
}

# Check: WORKDIR must not target /root/ in the final stage.
deny contains msg if {
	_is_dockerfile
	input[i].Stage == final_stage
	lower(input[i].Cmd) == "workdir"
	wd := input[i].Value[0]
	startswith(wd, "/root")
	not "no_root_paths" in exemptions
	msg := sprintf(
		"WORKDIR %s is under /root/ — inaccessible to non-root USER. Use /app/ instead.",
		[wd],
	)
}
