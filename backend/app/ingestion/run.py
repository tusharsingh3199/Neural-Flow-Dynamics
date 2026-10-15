import argparse
import json
import sys
from datetime import datetime

from sqlalchemy import create_engine

from app.ingestion.arco_era5 import ARCOEra5Adapter, ARCOEra5Config
from app.ingestion.gfs import GFSConfig, GFSGribAdapter
from app.ingestion.ibtracs import IBTracsNorthIndianAdapter
from app.ingestion.runner import run_ingestion
from app.ingestion.track_repository import TrackRepository
from app.settings import get_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest a verified environmental source.")
    parser.add_argument(
        "--source",
        required=True,
        choices=("arco_era5", "gfs", "ibtracs_ni"),
        help="Source adapter to run",
    )
    parser.add_argument("--start-time", help="Aware ISO-8601 start time (ARCO only)")
    parser.add_argument("--end-time", help="Aware ISO-8601 end time (ARCO only)")
    parser.add_argument(
        "--forecast-hours",
        nargs="+",
        type=int,
        help="Sorted GFS forecast hours to ingest as one complete run",
    )
    parser.add_argument(
        "--allow-era5t",
        action="store_true",
        help="Allow preliminary ERA5T coverage beyond stable ERA5",
    )
    args = parser.parse_args(argv)
    settings = get_settings()
    engine = create_engine(settings.database_url)
    try:
        if args.source == "arco_era5":
            if args.start_time is None or args.end_time is None:
                parser.error("--start-time and --end-time are required for arco_era5")
            if args.forecast_hours is not None:
                parser.error("--forecast-hours is only valid for gfs")
            config = ARCOEra5Config(
                output_root=settings.nfd_data_root / "arrays",
                start_time=datetime.fromisoformat(args.start_time.replace("Z", "+00:00")),
                end_time=datetime.fromisoformat(args.end_time.replace("Z", "+00:00")),
                allow_era5t=args.allow_era5t,
            )
            report = run_ingestion(ARCOEra5Adapter(config), engine)
            print(json.dumps(report.model_dump(mode="json"), indent=2))
        elif args.source == "gfs":
            if args.start_time is None or args.forecast_hours is None:
                parser.error("--start-time and --forecast-hours are required for gfs")
            if args.end_time is not None or args.allow_era5t:
                parser.error("--end-time and --allow-era5t are only valid for arco_era5")
            config = GFSConfig(
                init_time=datetime.fromisoformat(args.start_time.replace("Z", "+00:00")),
                forecast_hours=tuple(args.forecast_hours),
                output_root=settings.nfd_data_root / "arrays",
            )
            report = run_ingestion(GFSGribAdapter(config), engine)
            print(json.dumps(report.model_dump(mode="json"), indent=2))
        else:
            if (
                args.start_time is not None
                or args.end_time is not None
                or args.forecast_hours is not None
                or args.allow_era5t
            ):
                parser.error("time and forecast options are only valid for ARCO or GFS")
            adapter = IBTracsNorthIndianAdapter(settings.nfd_data_root / "raw" / "ibtracs")
            dataset, inserted = adapter.ingest(TrackRepository(engine))
            print(
                json.dumps(
                    {
                        "source_id": dataset.source_id,
                        "status": "inserted" if inserted else "unchanged",
                        "checksum": dataset.checksum,
                        "record_count": dataset.record_count,
                        "data_uri": dataset.data_uri,
                        "citation": dataset.citation,
                        "licence_note": dataset.licence_note,
                    },
                    indent=2,
                )
            )
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
