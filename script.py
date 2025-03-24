import os
import time
import docker
from datetime import datetime, timedelta
from CloudFlare import CloudFlare

CF_API_TOKEN = os.getenv("CF_API_TOKEN")
CF_ZONE_NAME = os.getenv("CF_ZONE_NAME")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 3600))  # Standard: 1 Stunde
INACTIVE_THRESHOLD_DAYS = int(os.getenv("INACTIVE_THRESHOLD_DAYS", 7))

cf = CloudFlare(token=CF_API_TOKEN)
client = docker.from_env()

zone_id = cf.zones.get(params={'name': CF_ZONE_NAME})[0]['id']

def update_dns(container):
    labels = container.labels

    if labels.get('dns.enable') == 'false':
        return

    if 'dns.enable' not in labels:
        add_dns_label(container)
        labels = container.labels

    if labels.get('dns.enable') != 'true':
        return

    dns_domain = labels.get('dns.domain')
    dns_type = labels.get('dns.type')
    dns_value = labels.get('dns.value')

    if not dns_domain or not dns_type or not dns_value:
        return

    existing_records = cf.zones.dns_records.get(zone_id, params={'name': dns_domain})
    if existing_records:
        print(f"[Update] Aktualisiere Eintrag: {dns_domain} -> {dns_value}")
        cf.zones.dns_records.put(zone_id, existing_records[0]['id'], data={
            'type': dns_type,
            'name': dns_domain,
            'content': dns_value,
            'proxied': False,
            'ttl': 120
        })
    else:
        print(f"[Neu] Erstelle Eintrag: {dns_domain} -> {dns_value}")
        cf.zones.dns_records.post(zone_id, data={
            'type': dns_type,
            'name': dns_domain,
            'content': dns_value,
            'proxied': False,
            'ttl': 120
        })

def add_dns_label(container):
    labels = container.labels

    if 'dns.enable' not in labels and all(key in labels for key in ['dns.domain', 'dns.type', 'dns.value']):
        print(f"[Auto-Label] Füge Label 'dns.enable=true' zu Container {container.name} hinzu")
        client.api.update_container(container.id, labels={**labels, 'dns.enable': 'true'})

def cleanup_inactive():
    cutoff = datetime.now() - timedelta(days=INACTIVE_THRESHOLD_DAYS)
    for container in client.containers.list(all=True):
        last_started = container.attrs['State']['StartedAt']
        last_started = datetime.strptime(last_started.split('.')[0], "%Y-%m-%dT%H:%M:%S")

        if last_started < cutoff:
            labels = container.labels
            if 'dns.domain' in labels:
                dns_domain = labels['dns.domain']
                print(f"[Cleanup] Entferne veralteten Eintrag: {dns_domain}")
                existing_records = cf.zones.dns_records.get(zone_id, params={'name': dns_domain})
                for record in existing_records:
                    cf.zones.dns_records.delete(zone_id, record['id'])

def main():
    while True:
        print("[Info] Starte DNS-Update Zyklus...")
        for container in client.containers.list(all=True):
            update_dns(container)
        cleanup_inactive()
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
