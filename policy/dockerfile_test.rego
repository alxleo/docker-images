package main

import rego.v1

# Inputs mirror conftest's Dockerfile parser: one {Cmd, Value, Stage} per
# instruction, comments as Cmd "comment".

_stage(cmds) := [{"Cmd": c[0], "Value": c[1], "Stage": 0} | some c in cmds]

# ---------- USER ----------

test_allow_numeric_non_root_user if {
	count(deny) == 0 with input as _stage([["from", ["alpine"]], ["user", ["1000:1000"]]])
}

test_deny_missing_user if {
	count(deny) == 1 with input as _stage([["from", ["alpine"]], ["cmd", ["true"]]])
}

test_deny_root_user_forms if {
	every user in ["root", "0", "0:0", "root:root", "ROOT", "0:1000"] {
		count(deny) == 1 with input as _stage([["from", ["alpine"]], ["user", [user]]])
	}
}

test_only_the_final_user_counts if {
	dockerfile := _stage([["from", ["alpine"]], ["user", ["0:0"]], ["run", ["apk add curl"]], ["user", ["1001:1001"]]])
	count(deny) == 0 with input as dockerfile
}

test_build_stage_root_is_ignored if {
	dockerfile := [
		{"Cmd": "from", "Value": ["golang", "AS", "build"], "Stage": 0},
		{"Cmd": "user", "Value": ["root"], "Stage": 0},
		{"Cmd": "from", "Value": ["alpine"], "Stage": 1},
		{"Cmd": "user", "Value": ["app"], "Stage": 1},
	]
	count(deny) == 0 with input as dockerfile
}

test_user_exemption if {
	dockerfile := _stage([["comment", ["# conftest:exempt=user_required -- needs CAP_NET_BIND"]], ["from", ["caddy"]]])
	count(deny) == 0 with input as dockerfile
}

# ---------- EXPOSE / HEALTHCHECK ----------

test_deny_expose_without_healthcheck if {
	count(deny) == 1 with input as _stage([["from", ["alpine"]], ["expose", ["8080"]], ["user", ["app"]]])
}

test_allow_expose_with_healthcheck if {
	dockerfile := _stage([["from", ["alpine"]], ["expose", ["8080"]], ["healthcheck", ["CMD", "true"]], ["user", ["app"]]])
	count(deny) == 0 with input as dockerfile
}

# ---------- /root paths ----------

test_deny_paths_under_root if {
	every instruction in [["copy", ["a", "/root/.config/"]], ["add", ["a", "/root"]], ["workdir", ["/root/app"]]] {
		count(deny) == 1 with input as _stage([["from", ["alpine"]], instruction, ["user", ["app"]]])
	}
}

test_allow_paths_that_only_share_the_prefix if {
	every instruction in [["copy", ["a", "/rootfs/etc/"]], ["workdir", ["/root-data"]]] {
		count(deny) == 0 with input as _stage([["from", ["alpine"]], instruction, ["user", ["app"]]])
	}
}
