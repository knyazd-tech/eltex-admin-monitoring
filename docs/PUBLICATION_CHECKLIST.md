# Publication checklist

Before changing repository visibility to public:

- Confirm the working tree and remote branch match.
- Run `tests/validate_package.py`.
- Run Prometheus rule validation.
- Run Compose validation.
- Confirm GitHub Actions passes.
- Search the complete repository for credentials and private IPs.
- Confirm `.env`, device dumps, cookies, and backups are absent.
- Review README, SECURITY, LICENSE, and CONTRIBUTING.
- Confirm ownership of all included source and dashboard files.
- Review firmware compatibility wording.
- Confirm the repository still uses the generic `eltex_*`
  namespace.
- Create a release from the intended immutable tag.
- Change visibility only after all checks pass.
