#!/usr/bin/env bash
# Docker published ports bypass UFW; filter external traffic before Docker accepts it.
set -euo pipefail
[[ ${EUID} -eq 0 ]] || { echo 'Run as root.' >&2; exit 1; }
for firewall in iptables ip6tables; do
    command -v "$firewall" >/dev/null || continue
    "$firewall" -w -S DOCKER-USER >/dev/null
    if ! "$firewall" -w -S VOLT-DEBT-INBOUND >/dev/null 2>&1; then
        "$firewall" -w -N VOLT-DEBT-INBOUND
    fi
    # These rules do not affect SSH, host listeners, or container outbound traffic.
    "$firewall" -w -C VOLT-DEBT-INBOUND -m conntrack --ctstate RELATED,ESTABLISHED -j RETURN 2>/dev/null ||
        "$firewall" -w -A VOLT-DEBT-INBOUND -m conntrack --ctstate RELATED,ESTABLISHED -j RETURN
    for port in 80 443; do
        "$firewall" -w -C VOLT-DEBT-INBOUND -p tcp -m conntrack --ctorigdstport "$port" -j RETURN 2>/dev/null ||
            "$firewall" -w -A VOLT-DEBT-INBOUND -p tcp -m conntrack --ctorigdstport "$port" -j RETURN
    done
    "$firewall" -w -C VOLT-DEBT-INBOUND -j DROP 2>/dev/null || "$firewall" -w -A VOLT-DEBT-INBOUND -j DROP
    for interface in eth0 eth1; do
        for bridge in 'br+' docker0; do
            "$firewall" -w -C DOCKER-USER -i "$interface" -o "$bridge" -j VOLT-DEBT-INBOUND 2>/dev/null ||
                "$firewall" -w -I DOCKER-USER 1 -i "$interface" -o "$bridge" -j VOLT-DEBT-INBOUND
        done
    done
done
echo 'Docker inbound policy installed: HTTP/HTTPS only on eth0/eth1.'
