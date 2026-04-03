# OPA unit tests for compose.rego
# Run: conftest verify -p policy/
package main

import rego.v1

# ---------- short-syntax volume tests ----------

test_deny_short_syntax_root_volume if {
	result := deny with input as {"services": {"web": {"volumes": ["./config:/root/.config:ro"]}}}
	count(result) > 0
}

test_allow_app_volume if {
	result := deny with input as {"services": {"web": {"volumes": ["./config:/app/config:ro"]}}}
	count(result) == 0
}

test_deny_named_volume_root if {
	result := deny with input as {"services": {"web": {"volumes": ["cache-vol:/root/.cache"]}}}
	count(result) > 0
}

# ---------- long-syntax volume tests ----------

test_deny_long_syntax_root_volume if {
	result := deny with input as {"services": {"web": {"volumes": [{"type": "bind", "source": "./config", "target": "/root/.config"}]}}}
	count(result) > 0
}

test_allow_long_syntax_app_volume if {
	result := deny with input as {"services": {"web": {"volumes": [{"type": "bind", "source": "./config", "target": "/app/.config"}]}}}
	count(result) == 0
}

# ---------- tmpfs tests ----------

test_deny_tmpfs_root if {
	result := deny with input as {"services": {"web": {"tmpfs": ["/root/.npm:exec"]}}}
	count(result) > 0
}

test_deny_tmpfs_root_no_options if {
	result := deny with input as {"services": {"web": {"tmpfs": ["/root/.cache"]}}}
	count(result) > 0
}

test_allow_tmpfs_tmp if {
	result := deny with input as {"services": {"web": {"tmpfs": ["/tmp/.npm:exec"]}}}
	count(result) == 0
}

# ---------- working_dir tests ----------

test_deny_working_dir_root if {
	result := deny with input as {"services": {"web": {"working_dir": "/root/app"}}}
	count(result) > 0
}

test_deny_working_dir_root_exact if {
	result := deny with input as {"services": {"web": {"working_dir": "/root"}}}
	count(result) > 0
}

test_allow_working_dir_app if {
	result := deny with input as {"services": {"web": {"working_dir": "/app"}}}
	count(result) == 0
}

# ---------- exemption tests ----------

test_exemption_volume if {
	result := deny with input as {"services": {"web": {
		"x-conftest-exempt": ["no_root_volumes"],
		"volumes": ["./config:/root/.config"],
	}}}
	count(result) == 0
}

test_exemption_tmpfs if {
	result := deny with input as {"services": {"web": {
		"x-conftest-exempt": ["no_root_volumes"],
		"tmpfs": ["/root/.cache"],
	}}}
	count(result) == 0
}

test_exemption_working_dir if {
	result := deny with input as {"services": {"web": {
		"x-conftest-exempt": ["no_root_working_dir"],
		"working_dir": "/root",
	}}}
	count(result) == 0
}

test_wrong_exemption_does_not_suppress if {
	result := deny with input as {"services": {"web": {
		"x-conftest-exempt": ["no_root_working_dir"],
		"volumes": ["./config:/root/.config"],
	}}}
	count(result) > 0
}

# ---------- multi-service tests ----------

test_multiple_services_one_bad if {
	result := deny with input as {"services": {
		"good": {"volumes": ["./config:/app/config"]},
		"bad": {"volumes": ["./config:/root/.config"]},
	}}
	count(result) == 1
}

test_message_includes_service_name if {
	result := deny with input as {"services": {"my-reviewer": {"volumes": ["./config:/root/.config"]}}}
	some msg in result
	contains(msg, "my-reviewer")
}

# ---------- edge cases ----------

test_no_services_key if {
	result := deny with input as {"version": "3"}
	count(result) == 0
}

test_service_with_no_volumes if {
	result := deny with input as {"services": {"web": {"image": "nginx"}}}
	count(result) == 0
}
