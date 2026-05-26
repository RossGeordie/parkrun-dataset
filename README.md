# parkrun-dataset

> _After building this in Power BI we have built a this whole pipeline in OpenSource._

## What this is

This repository is an open-source pipeline for ingesting parkrun data
(results & volunteer records) into PostgreSQL and generating open-source
Power BI alternatives (interactive web-based report packs).

It replaces the proprietary Microsoft stack with fully open-source
alternatives while maintaining full data fidelity and reporting capabilities.

## Stack

- **Storage**: PostgreSQL (LXC 100 on the host estate)
- **Analysis**: Python + Pandas/Polars
- **Reporting**: FastAPI + HTML/JS (or Dash)
- **Infrastructure**: CachyOS host, UniFi-managed network, Proxmox LXC

## Quick Start

```bash
pip install -e .
cp configs/db.example.yaml configs/db.yaml
python scripts/etl.py --event "your-parkrun-name"
python scripts/query.py --event "your-parkrun-name" --output report.html
```

## Documentation

See [docs/architecture.md](docs/architecture.md) for the full data model
and reporting flow.

## License

MIT License - see [LICENSE](LICENSE) for details.
