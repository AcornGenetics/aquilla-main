#!/usr/bin/env bash

set -euo pipefail

if [[ -f /opt/aquila/config/grafana.env ]]; then
  # shellcheck source=/dev/null
  source /opt/aquila/config/grafana.env
fi

: "${GCLOUD_HOSTED_METRICS_ID:?Missing GCLOUD_HOSTED_METRICS_ID}"
: "${GCLOUD_HOSTED_METRICS_URL:?Missing GCLOUD_HOSTED_METRICS_URL}"
: "${GCLOUD_HOSTED_LOGS_ID:?Missing GCLOUD_HOSTED_LOGS_ID}"
: "${GCLOUD_HOSTED_LOGS_URL:?Missing GCLOUD_HOSTED_LOGS_URL}"
: "${GCLOUD_FM_URL:?Missing GCLOUD_FM_URL}"
: "${GCLOUD_FM_POLL_FREQUENCY:?Missing GCLOUD_FM_POLL_FREQUENCY}"
: "${GCLOUD_FM_HOSTED_ID:?Missing GCLOUD_FM_HOSTED_ID}"
: "${ARCH:?Missing ARCH}"
: "${GCLOUD_RW_API_KEY:?Missing GCLOUD_RW_API_KEY}"

GCLOUD_HOSTED_METRICS_ID="$GCLOUD_HOSTED_METRICS_ID" \
  GCLOUD_HOSTED_METRICS_URL="$GCLOUD_HOSTED_METRICS_URL" \
  GCLOUD_HOSTED_LOGS_ID="$GCLOUD_HOSTED_LOGS_ID" \
  GCLOUD_HOSTED_LOGS_URL="$GCLOUD_HOSTED_LOGS_URL" \
  GCLOUD_FM_URL="$GCLOUD_FM_URL" \
  GCLOUD_FM_POLL_FREQUENCY="$GCLOUD_FM_POLL_FREQUENCY" \
  GCLOUD_FM_HOSTED_ID="$GCLOUD_FM_HOSTED_ID" \
  ARCH="$ARCH" \
  GCLOUD_RW_API_KEY="$GCLOUD_RW_API_KEY" \
  /bin/sh -c "$(curl -fsSL https://storage.googleapis.com/cloud-onboarding/alloy/scripts/install-linux.sh)"

CONFIG_PATH="/etc/alloy/config.alloy"

if ! sudo test -f "$CONFIG_PATH"; then
  echo "Alloy config not found at $CONFIG_PATH"
  exit 1
fi

if sudo grep -q "integrations/raspberrypi-node" "$CONFIG_PATH"; then
  echo "Raspberry Pi integration already present in $CONFIG_PATH"
  exit 0
fi

timestamp="$(date +%Y%m%d%H%M%S)"
sudo cp "$CONFIG_PATH" "${CONFIG_PATH}.bak.${timestamp}"

cat <<'EOF' | sudo tee -a "$CONFIG_PATH" >/dev/null

prometheus.exporter.unix "integrations_node_exporter" { }

discovery.relabel "integrations_node_exporter" {
	targets = prometheus.exporter.unix.integrations_node_exporter.targets

	rule {
		target_label = "instance"
		replacement  = constants.hostname
	}

	rule {
		target_label = "job"
		replacement  = "integrations/raspberrypi-node"
	}
}

prometheus.scrape "integrations_node_exporter" {
	targets    = discovery.relabel.integrations_node_exporter.output
	forward_to = [prometheus.relabel.integrations_node_exporter.receiver]
	job_name   = "integrations/node_exporter"
}

prometheus.relabel "integrations_node_exporter" {
	forward_to = [prometheus.remote_write.metrics_service.receiver]

	rule {
		source_labels = ["__name__"]
		regex         = "up|node_boot_time_seconds|node_cpu_seconds_total|node_disk_io_time_seconds_total|node_disk_io_time_weighted_seconds_total|node_disk_read_bytes_total|node_disk_written_bytes_total|node_filesystem_avail_bytes|node_filesystem_files|node_filesystem_files_free|node_filesystem_readonly|node_filesystem_size_bytes|node_hwmon_temp_celsius|node_load1|node_load15|node_load5|node_memory_Buffers_bytes|node_memory_Cached_bytes|node_memory_MemAvailable_bytes|node_memory_MemFree_bytes|node_memory_MemTotal_bytes|node_memory_Slab_bytes|node_memory_SwapTotal_bytes|node_network_receive_bytes_total|node_network_receive_drop_total|node_network_receive_errs_total|node_network_receive_packets_total|node_network_transmit_bytes_total|node_network_transmit_drop_total|node_network_transmit_errs_total|node_network_transmit_packets_total|node_os_info|node_systemd_unit_state|node_uname_info|node_vmstat_pgmajfault"
		action        = "keep"
	}
}

discovery.relabel "logs_integrations_integrations_node_exporter_journal_scrape" {
	targets = []

	rule {
		source_labels = ["__journal__systemd_unit"]
		target_label  = "unit"
	}

	rule {
		source_labels = ["__journal__boot_id"]
		target_label  = "boot_id"
	}

	rule {
		source_labels = ["__journal__transport"]
		target_label  = "transport"
	}

	rule {
		source_labels = ["__journal_priority_keyword"]
		target_label  = "level"
	}
}

loki.source.journal "logs_integrations_integrations_node_exporter_journal_scrape" {
	max_age       = "24h0m0s"
	relabel_rules = discovery.relabel.logs_integrations_integrations_node_exporter_journal_scrape.rules
	forward_to    = [loki.write.grafana_cloud_loki.receiver]
	labels        = {
		instance = constants.hostname,
		job      = "integrations/raspberrypi-node",
	}
}

local.file_match "logs_integrations_integrations_node_exporter_direct_scrape" {
	path_targets = [{
		__address__ = "localhost",
		__path__    = "/var/log/{syslog,messages,*.log}",
		instance    = constants.hostname,
		job         = "integrations/raspberrypi-node",
	}]
}

loki.source.file "logs_integrations_integrations_node_exporter_direct_scrape" {
	targets    = local.file_match.logs_integrations_integrations_node_exporter_direct_scrape.targets
	forward_to = [loki.write.grafana_cloud_loki.receiver]
}
EOF

echo "Raspberry Pi integration appended to $CONFIG_PATH"
