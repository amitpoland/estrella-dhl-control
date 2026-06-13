# B7 Backup System Runbook

## Overview

The B7 Automated Backup Program provides automated SQLite database backups with integrity validation and retention management for the Estrella PZ service.

**Key features:**
- Online SQLite backup using WAL checkpoint + backup API
- Timestamped backup directories with JSON manifests
- Integrity validation through restore simulation
- Retention policy: 7 daily, 4 weekly, 12 monthly
- Admin web interface and CLI access

## Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────────┐
│ Windows Task    │───▶│ run_backup.py    │───▶│ C:\PZ-backups\      │
│ Scheduler       │    │ (CLI entry)      │    │ YYYY-MM-DD-HHMMSS/  │
└─────────────────┘    └──────────────────┘    └─────────────────────┘
                                │                         │
┌─────────────────┐              │               ┌────────▼─────────────┐
│ Admin Web UI    │◀─────────────┘               │ manifest.json        │
│ /admin/backup/* │                              │ *.db backup files    │
└─────────────────┘                              └──────────────────────┘
```

## Database Registry

The system backs up these databases from `storage_root` and auth paths:

| Database | Source Path | Role |
|---|---|---|
| `packing` | `storage_root/packing.db` | Packing list data |
| `warehouse` | `storage_root/warehouse.db` | Warehouse scans |
| `documents` | `storage_root/documents.db` | Document registry |
| `wfirma` | `storage_root/wfirma.db` | wFirma cache |
| `correction_registry` | `storage_root/correction_registry.db` | Operator corrections |
| `intake_lineage` | `storage_root/intake_lineage.db` | Intake tracking |
| `proforma_links` | `storage_root/proforma_links.db` | Proforma associations |
| `tracking_events` | `storage_root/tracking_events.db` | DHL tracking |
| `reservation_queue` | `storage_root/reservation_queue.db` | Product reservations |
| `customer_master` | `storage_root/customer_master.sqlite` | Customer data |
| `master_audit` | `storage_root/master_audit.sqlite` | Audit records |
| `master_data` | `storage_root/master_data.sqlite` | HS codes, units |
| `suppliers` | `storage_root/suppliers.sqlite` | Supplier registry |
| `users` | `storage_root/users.db` or `auth_db_path` | Authentication |
| `packing_resolutions` | `storage_root/packing_resolutions.sqlite` | Resolution verdicts |

## Scheduling Setup (Windows Task Scheduler)

### Basic Backup (Daily at 2:00 AM)

```cmd
schtasks /create /tn "PZ-Backup" /tr "C:\Python39\python.exe C:\PZ\scripts\run_backup.py" /sc daily /st 02:00 /ru SYSTEM /f
```

### Backup with Retention (Daily at 2:00 AM)

```cmd
schtasks /create /tn "PZ-Backup-Prune" /tr "C:\Python39\python.exe C:\PZ\scripts\run_backup.py --prune" /sc daily /st 02:00 /ru SYSTEM /f
```

### View Scheduled Task

```cmd
schtasks /query /tn "PZ-Backup" /v
```

### Delete Task

```cmd
schtasks /delete /tn "PZ-Backup" /f
```

## Manual Operations

### Run Backup

```cmd
cd C:\PZ\service
python scripts\run_backup.py
```

### Run Backup with Custom Location

```cmd
python scripts\run_backup.py --backup-root "D:\Backups"
```

### Apply Retention Policy

```cmd
python scripts\run_backup.py --prune
```

### Validate Backup

```cmd
python scripts\run_backup.py --validate 2026-06-12-143022
```

### Preview Retention (Dry Run)

```powershell
# Use admin web interface or API:
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/admin/backup/prune?dry_run=true" -Method POST -Headers @{"X-API-Key"="your-key"}
```

## Web Admin Interface

Access via authenticated admin user:

- **POST** `/api/v1/admin/backup/run` — Run backup now
- **GET** `/api/v1/admin/backup/list` — List all backups
- **POST** `/api/v1/admin/backup/validate` — Validate backup
- **POST** `/api/v1/admin/backup/prune` — Apply retention (add `?dry_run=true` to preview)

## Backup Validation

### Automatic Checks

Each validation performs:
1. **Restore simulation** — Copy to temp directory
2. **SQLite integrity** — `PRAGMA integrity_check`
3. **Sentinel query** — `SELECT count(*) FROM sqlite_master`
4. **SHA256 verification** — Against manifest checksum
5. **Cleanup** — Remove temp files

### Reading Results

```json
{
  "overall_verdict": "PASS",
  "backup_id": "2026-06-12-143022",
  "files": {
    "packing": {
      "status": "PASS",
      "message": "All checks passed (sentinel: 15 objects)",
      "integrity_check": "PASS",
      "sentinel_query": "PASS",
      "sha256_check": "PASS"
    }
  }
}
```

## Restore Procedure

### 1. Stop PZ Service

```cmd
sc stop PZService
```

### 2. Backup Current State

```cmd
robocopy "C:\PZ\storage" "C:\PZ\storage-backup-$(Get-Date -Format 'yyyy-MM-dd-HHmmss')" /E
```

### 3. Restore from Backup

```cmd
# Copy backup files to storage directory
robocopy "C:\PZ-backups\2026-06-12-143022" "C:\PZ\storage" *.db /COPY:DAT

# Note: Backup files are named {db_name}.db, may need to rename:
# customer_master.db → customer_master.sqlite
# master_audit.db → master_audit.sqlite
# etc.
```

### 4. Start PZ Service

```cmd
sc start PZService
```

### 5. Verify Health

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/debug/health-full" -Headers @{"X-API-Key"="your-key"}
```

Check dimension 13 (backup_freshness) and other storage-related checks.

## Retention Policy

### Rules
- **Daily**: Keep last 7 backups (one per day)
- **Weekly**: Keep last 4 backups (one per ISO week)
- **Monthly**: Keep last 12 backups (one per month)

### Union Strategy
Final keep set = Daily ∪ Weekly ∪ Monthly. A backup kept by any rule is preserved.

### Example Retention

For backups spanning 3 months:
- Days 1-7: Keep all (daily rule)
- Weeks 2-4: Keep latest per week (weekly rule)
- Months 1-3: Keep latest per month (monthly rule)

## Monitoring

### Guardian Health Check

Dimension 13 (`backup_freshness`) in `/api/v1/debug/health-full`:

- **ok**: Latest backup < 26 hours old
- **degraded**: Latest backup > 26 hours old
- **missing**: No valid backup manifests found

### Log Messages

Backup runs log to service logs:
- Backup completion with file counts
- Failed files with error details
- Retention results (kept/deleted counts)

## Disk Space Management

### Estimate Storage Requirements

Average database sizes (production):
- Total per backup: ~500MB - 2GB
- Daily retention (7): 3-14GB
- Weekly/Monthly (16): 8-32GB
- **Total estimate**: 15-50GB for full retention

### Cleanup Commands

```cmd
# Emergency cleanup - delete backups older than 30 days
forfiles /p "C:\PZ-backups" /c "cmd /c if @isdir==TRUE rmdir /s /q @path" /d -30

# Check disk usage
dir "C:\PZ-backups" /s
```

## Troubleshooting

### Common Issues

#### Backup Fails with "Database is locked"

**Cause**: Active transaction holding write lock
**Solution**: Wait for active operations to complete, ensure WAL checkpoint

#### Validation Fails with "Integrity check failed"

**Cause**: Corrupted source database or backup
**Solution**: 
1. Validate source database directly
2. Re-run backup if source is healthy
3. Check disk space and storage health

#### Retention Not Running

**Cause**: Scheduled task not configured or failed
**Solution**: Check Task Scheduler status, verify script path

#### "No valid backup manifests found"

**Cause**: Backup directory empty or corrupted manifests
**Solution**: Check `C:\PZ-backups` exists, run manual backup

### Log Locations

- **Service logs**: Windows Event Viewer → Applications and Services → PZService
- **Task Scheduler logs**: Event Viewer → Windows Logs → System (Task Scheduler category)
- **Backup CLI output**: Console or redirect to file

### Debug Commands

```cmd
# Test backup without scheduling
python scripts\run_backup.py --backup-root "C:\temp\test-backup"

# Validate specific backup
python scripts\run_backup.py --validate 2026-06-12-143022

# Check what would be deleted (dry run)
# Use admin API with dry_run=true parameter
```

## Security Notes

- Backup root `C:\PZ-backups` should have restricted access (SYSTEM, Administrators only)
- Backups contain sensitive business data (customer info, financial records)
- Consider encryption for backups moved to network storage
- Admin API endpoints require admin role authentication

## Contact

For issues with B7 Backup System:
1. Check Guardian health dimension 13
2. Review Windows Event Viewer logs
3. Validate recent backup manually
4. Contact system administrator if restore needed