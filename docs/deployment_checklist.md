# Shared Deployment Checklist

Planning only; do not deploy from this checklist.

- [ ] VM/network placement approved
- [ ] TLS/reverse proxy configured
- [ ] Role model defined: viewer, analyst, approver, administrator
- [ ] HSDES read identity configured
- [ ] HSDES write identity isolated and disabled by default
- [ ] Shared KB backup/restore tested
- [ ] RCA history retention defined
- [ ] Audit trail immutable storage configured
- [ ] Git integration uses protected credentials
- [ ] Secrets stored in approved secret manager
- [ ] Monitoring/alerting and log retention defined
- [ ] Disaster recovery and rollback tested
- [ ] Security review completed
- [ ] No command execution enabled for AutoHSD recommendations
