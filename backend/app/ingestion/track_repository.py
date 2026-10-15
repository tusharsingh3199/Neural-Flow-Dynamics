from collections.abc import Iterable
from datetime import UTC

from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ingestion.database import CycloneTrackPointRow, TrackDatasetRow
from app.ingestion.tracks import TrackDataset, TrackPoint


class TrackRepository:
    def __init__(self, engine: Engine, *, batch_size: int = 1000) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self._engine = engine
        self._batch_size = batch_size

    def insert(self, dataset: TrackDataset, points: Iterable[TrackPoint]) -> bool:
        with Session(self._engine) as session:
            existing = session.scalar(
                select(TrackDatasetRow.id).where(TrackDatasetRow.checksum == dataset.checksum)
            )
            if existing is not None:
                return False
            row = TrackDatasetRow(
                source_id=dataset.source_id,
                source_url=dataset.source_url,
                version=dataset.version,
                basin=dataset.basin,
                checksum=dataset.checksum,
                data_uri=dataset.data_uri,
                licence_note=dataset.licence_note,
                citation=dataset.citation,
                field_units=dataset.field_units,
                record_count=dataset.record_count,
                retrieved_at=dataset.retrieved_at,
                ingested_at=dataset.ingested_at,
            )
            session.add(row)
            try:
                session.flush()
                count = 0
                batch: list[CycloneTrackPointRow] = []
                for point in points:
                    batch.append(self._to_row(row.id, point))
                    if len(batch) >= self._batch_size:
                        session.add_all(batch)
                        count += len(batch)
                        batch.clear()
                if batch:
                    session.add_all(batch)
                    count += len(batch)
                if count != dataset.record_count:
                    raise ValueError(
                        f"track dataset declares {dataset.record_count} points but parsed {count}"
                    )
                session.commit()
            except IntegrityError:
                session.rollback()
                existing = session.scalar(
                    select(TrackDatasetRow.id).where(TrackDatasetRow.checksum == dataset.checksum)
                )
                if existing is not None:
                    return False
                raise
        return True

    @staticmethod
    def _to_row(dataset_id: str, point: TrackPoint) -> CycloneTrackPointRow:
        return CycloneTrackPointRow(
            dataset_id=dataset_id,
            sid=point.sid,
            season=point.season,
            basin=point.basin,
            subbasin=point.subbasin,
            name=point.name,
            valid_time=point.valid_time,
            latitude=point.latitude,
            longitude=point.longitude,
            track_type=point.track_type,
            wmo_wind=point.wmo_wind,
            wmo_wind_unit=point.wmo_wind_unit,
            wmo_pressure=point.wmo_pressure,
            wmo_pressure_unit=point.wmo_pressure_unit,
            wmo_agency=point.wmo_agency,
            newdelhi_wind=point.newdelhi_wind,
            newdelhi_wind_unit=point.newdelhi_wind_unit,
            newdelhi_pressure=point.newdelhi_pressure,
            newdelhi_pressure_unit=point.newdelhi_pressure_unit,
            raw_fields=point.raw_fields,
            field_units=point.field_units,
        )

    @staticmethod
    def _aware(value):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value

    def list_storms(self) -> list[dict[str, object]]:
        statement = (
            select(
                CycloneTrackPointRow.sid,
                CycloneTrackPointRow.season,
                CycloneTrackPointRow.name,
                CycloneTrackPointRow.basin,
                func.min(CycloneTrackPointRow.valid_time).label("start_time"),
                func.max(CycloneTrackPointRow.valid_time).label("end_time"),
                func.count(CycloneTrackPointRow.id).label("point_count"),
            )
            .group_by(
                CycloneTrackPointRow.sid,
                CycloneTrackPointRow.season,
                CycloneTrackPointRow.name,
                CycloneTrackPointRow.basin,
            )
            .order_by(CycloneTrackPointRow.season, CycloneTrackPointRow.sid)
        )
        with Session(self._engine) as session:
            rows = session.execute(statement).all()
        return [
            {
                "sid": row.sid,
                "season": row.season,
                "name": row.name,
                "basin": row.basin,
                "start_time": self._aware(row.start_time),
                "end_time": self._aware(row.end_time),
                "point_count": row.point_count,
            }
            for row in rows
        ]

    def get_track(self, sid: str) -> tuple[TrackDatasetRow, list[TrackPoint]] | None:
        dataset_statement = (
            select(TrackDatasetRow)
            .join(CycloneTrackPointRow, CycloneTrackPointRow.dataset_id == TrackDatasetRow.id)
            .where(CycloneTrackPointRow.sid == sid)
            .order_by(TrackDatasetRow.ingested_at.desc())
            .limit(1)
        )
        with Session(self._engine) as session:
            dataset = session.scalar(dataset_statement)
            if dataset is None:
                return None
            rows = session.scalars(
                select(CycloneTrackPointRow)
                .where(
                    CycloneTrackPointRow.dataset_id == dataset.id,
                    CycloneTrackPointRow.sid == sid,
                )
                .order_by(CycloneTrackPointRow.valid_time)
            ).all()
        points = [
            TrackPoint(
                sid=row.sid,
                season=row.season,
                basin=row.basin,
                subbasin=row.subbasin,
                name=row.name,
                valid_time=self._aware(row.valid_time),
                latitude=row.latitude,
                longitude=row.longitude,
                track_type=row.track_type,
                wmo_wind=row.wmo_wind,
                wmo_wind_unit=row.wmo_wind_unit,
                wmo_pressure=row.wmo_pressure,
                wmo_pressure_unit=row.wmo_pressure_unit,
                wmo_agency=row.wmo_agency,
                newdelhi_wind=row.newdelhi_wind,
                newdelhi_wind_unit=row.newdelhi_wind_unit,
                newdelhi_pressure=row.newdelhi_pressure,
                newdelhi_pressure_unit=row.newdelhi_pressure_unit,
                raw_fields=row.raw_fields,
                field_units=row.field_units,
            )
            for row in rows
        ]
        return dataset, points