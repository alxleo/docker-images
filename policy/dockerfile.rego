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
	not "user" in final_stage_cmds
	not "user_required" in exemptions
	msg := "Dockerfile must have a USER directive in the final stage. Add USER 1000 before ENTRYPOINT."
}

deny contains msg if {
	last_user in {"root", "0"}
	not "user_required" in exemptions
	msg := sprintf("Final USER should not be root (found: %s). Use a non-root UID.", [last_user])
}

# Check: EXPOSE implies HEALTHCHECK in the same stage
deny contains msg if {
	"expose" in final_stage_cmds
	not "healthcheck" in final_stage_cmds
	not "healthcheck_required" in exemptions
	msg := "Dockerfile has EXPOSE but no HEALTHCHECK. Add a HEALTHCHECK directive."
}
