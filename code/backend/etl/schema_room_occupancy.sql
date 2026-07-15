CREATE TABLE IF NOT EXISTS fact_room_occupancy (
    occupancy_id             TEXT PRIMARY KEY,
    semester_id              TEXT NOT NULL,
    activity_date            TEXT NOT NULL,
    weekday                  INTEGER NOT NULL,
    start_time               TEXT NOT NULL,
    end_time                 TEXT NOT NULL,
    start_minute             INTEGER NOT NULL,
    end_minute               INTEGER NOT NULL,
    duration_minutes         INTEGER NOT NULL,
    time_band                TEXT NOT NULL,
    period_start             INTEGER,
    period_end               INTEGER,
    room_name                TEXT NOT NULL,
    building_name            TEXT,
    building_mapping_status  TEXT NOT NULL,
    activity_type            TEXT NOT NULL,
    activity_name_masked     TEXT NOT NULL,
    source_activity_code     TEXT,
    course_id                TEXT,
    is_evening               INTEGER NOT NULL DEFAULT 0,
    overlap_count            INTEGER NOT NULL DEFAULT 0,
    pii_redacted             INTEGER NOT NULL DEFAULT 0,
    raw_activity_hash        TEXT NOT NULL,
    source_file              TEXT NOT NULL,
    source_row_number        INTEGER NOT NULL,
    import_batch_id          TEXT NOT NULL,
    imported_at              TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_room_occ_sem_date
    ON fact_room_occupancy(semester_id, activity_date);
CREATE INDEX IF NOT EXISTS idx_room_occ_room_date
    ON fact_room_occupancy(room_name, activity_date, start_minute, end_minute);
CREATE INDEX IF NOT EXISTS idx_room_occ_building
    ON fact_room_occupancy(semester_id, building_name);
CREATE INDEX IF NOT EXISTS idx_room_occ_type
    ON fact_room_occupancy(semester_id, activity_type);

CREATE TABLE IF NOT EXISTS fact_room_occupancy_period (
    occupancy_id      TEXT NOT NULL,
    period_index      INTEGER NOT NULL,
    overlap_minutes   INTEGER NOT NULL,
    PRIMARY KEY (occupancy_id, period_index),
    FOREIGN KEY (occupancy_id) REFERENCES fact_room_occupancy(occupancy_id)
);

CREATE INDEX IF NOT EXISTS idx_room_occ_period
    ON fact_room_occupancy_period(period_index, occupancy_id);
CREATE INDEX IF NOT EXISTS idx_room_occ_period_occupancy
    ON fact_room_occupancy_period(occupancy_id, period_index);

CREATE TABLE IF NOT EXISTS dim_observed_room (
    room_name                TEXT PRIMARY KEY,
    building_name            TEXT,
    building_mapping_status  TEXT NOT NULL,
    first_seen_date           TEXT NOT NULL,
    last_seen_date            TEXT NOT NULL,
    observed_days             INTEGER NOT NULL,
    occupancy_count           INTEGER NOT NULL,
    source_system             TEXT NOT NULL,
    refreshed_at              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS etl_room_occupancy_batch (
    import_batch_id          TEXT PRIMARY KEY,
    source_file              TEXT NOT NULL,
    source_sha256            TEXT NOT NULL,
    semester_id              TEXT NOT NULL,
    imported_at              TEXT NOT NULL,
    source_rows              INTEGER NOT NULL,
    loaded_rows              INTEGER NOT NULL,
    observed_rooms           INTEGER NOT NULL,
    mapped_building_rows     INTEGER NOT NULL,
    pending_building_rows    INTEGER NOT NULL,
    pii_redacted_rows        INTEGER NOT NULL,
    overlap_rows             INTEGER NOT NULL,
    invalid_rows             INTEGER NOT NULL,
    quality_json             TEXT NOT NULL
);
