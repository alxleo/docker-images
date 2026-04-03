# Docker Compose structural policies.
#
# Enforces invariants for services defined in docker-compose YAML files:
# - No volume mounts (bind, named, tmpfs) targeting /root/ in containers
# - No working_dir set to /root/ or subdirectories
#
# When a non-root USER is set in the Dockerfile (UID 1000), /root/ is
# inaccessible (mode 700). Mounts targeting /root/ cause PermissionError
# crash loops at runtime.
#
# Exemptions via x-conftest-exempt extension field on the service:
#   x-conftest-exempt: [no_root_volumes]
#   x-conftest-exempt: [no_root_working_dir]
#
# Run: conftest test --parser yaml -p policy/ -- test/docker-compose*.yml examples/docker-compose.yml
package main

import rego.v1

# ---------- helpers ----------

# Extract container target path from short-syntax volume string.
# Format: [host_path:]container_path[:mode]
_container_target(vol_str) := parts[1] if {
	parts := split(vol_str, ":")
	count(parts) >= 2
	startswith(parts[1], "/")
}

_container_target(vol_str) := vol_str if {
	parts := split(vol_str, ":")
	count(parts) == 1
	startswith(vol_str, "/")
}

# Check if a path starts with /root/ or is exactly /root
_targets_root(path) if startswith(path, "/root/")

_targets_root(path) if path == "/root"

# Collect exemptions for a service
_service_exempt(svc_def, rule) if {
	some exemption in svc_def["x-conftest-exempt"]
	exemption == rule
}

# ---------- volume mount rules ----------

# Short syntax volumes: "source:target[:mode]"
deny contains msg if {
	some svc_name, svc_def in input.services
	some vol in svc_def.volumes
	is_string(vol)
	target := _container_target(vol)
	_targets_root(target)
	not _service_exempt(svc_def, "no_root_volumes")
	msg := sprintf(
		"Service '%s' mounts volume to %s — inaccessible with non-root USER. Use $HOME paths instead.",
		[svc_name, target],
	)
}

# Long syntax volumes: {type: bind|volume, source: ..., target: ...}
deny contains msg if {
	some svc_name, svc_def in input.services
	some vol in svc_def.volumes
	is_object(vol)
	target := vol.target
	_targets_root(target)
	not _service_exempt(svc_def, "no_root_volumes")
	msg := sprintf(
		"Service '%s' mounts volume to %s — inaccessible with non-root USER. Use $HOME paths instead.",
		[svc_name, target],
	)
}

# tmpfs entries targeting /root/
deny contains msg if {
	some svc_name, svc_def in input.services
	some tmpfs_entry in svc_def.tmpfs
	is_string(tmpfs_entry)
	mount_point := split(tmpfs_entry, ":")[0]
	_targets_root(mount_point)
	not _service_exempt(svc_def, "no_root_volumes")
	msg := sprintf(
		"Service '%s' has tmpfs at %s — inaccessible with non-root USER. Use /tmp/ instead.",
		[svc_name, mount_point],
	)
}

# ---------- working_dir rule ----------

deny contains msg if {
	some svc_name, svc_def in input.services
	wd := svc_def.working_dir
	_targets_root(wd)
	not _service_exempt(svc_def, "no_root_working_dir")
	msg := sprintf(
		"Service '%s' sets working_dir to %s — inaccessible with non-root USER. Use /app/ instead.",
		[svc_name, wd],
	)
}
