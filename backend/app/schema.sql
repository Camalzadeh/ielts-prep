-- IELTS prep SQLite schema (see ARCHITECTURE.md §2). Applied on every startup; must stay idempotent.

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tests (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    module TEXT,
    title TEXT,
    series TEXT,
    book INTEGER,
    test_no INTEGER,
    source TEXT,
    source_url TEXT,
    question_count INTEGER,
    file_path TEXT,
    data_json TEXT,
    imported_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_tests_type ON tests(type);

CREATE TABLE IF NOT EXISTS mock_exams (
    id INTEGER PRIMARY KEY,
    created_at TEXT,
    finished_at TEXT,
    status TEXT DEFAULT 'in_progress',
    plan_json TEXT,
    listening_band REAL,
    reading_band REAL,
    writing_band REAL,
    speaking_band REAL,
    overall_band REAL
);

CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY,
    test_id TEXT REFERENCES tests(id),
    type TEXT,
    mock_id INTEGER REFERENCES mock_exams(id) ON DELETE SET NULL,
    mode TEXT DEFAULT 'practice',
    started_at TEXT,
    finished_at TEXT,
    duration_sec INTEGER,
    status TEXT DEFAULT 'in_progress',
    raw_score INTEGER,
    total INTEGER,
    band REAL,
    answers_json TEXT,
    highlights_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_attempts_test ON attempts(test_id);
CREATE INDEX IF NOT EXISTS ix_attempts_mock ON attempts(mock_id);

CREATE TABLE IF NOT EXISTS attempt_answers (
    id INTEGER PRIMARY KEY,
    attempt_id INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
    part INTEGER,
    question_number INTEGER,
    question_type TEXT,
    user_answer TEXT,
    correct_answers TEXT,
    is_correct INTEGER,
    question_text TEXT
);
CREATE INDEX IF NOT EXISTS ix_attempt_answers_attempt ON attempt_answers(attempt_id);

CREATE TABLE IF NOT EXISTS writing_prompts (
    id INTEGER PRIMARY KEY,
    task INTEGER,
    module TEXT DEFAULT 'academic',
    essay_type TEXT,
    prompt TEXT NOT NULL,
    image_path TEXT,
    image_description TEXT,
    source TEXT,
    source_date TEXT,
    tags TEXT,
    UNIQUE(prompt)
);

CREATE TABLE IF NOT EXISTS writing_submissions (
    id INTEGER PRIMARY KEY,
    prompt_id INTEGER REFERENCES writing_prompts(id),
    mock_id INTEGER REFERENCES mock_exams(id) ON DELETE SET NULL,
    text TEXT,
    word_count INTEGER,
    time_spent_sec INTEGER,
    created_at TEXT,
    origin TEXT DEFAULT 'app'
);
CREATE INDEX IF NOT EXISTS ix_writing_submissions_prompt ON writing_submissions(prompt_id);

CREATE TABLE IF NOT EXISTS speaking_questions (
    id INTEGER PRIMARY KEY,
    part INTEGER NOT NULL,
    topic TEXT NOT NULL DEFAULT '',
    question TEXT NOT NULL,
    cue_points_json TEXT,
    follow_up_json TEXT,
    season TEXT,
    source TEXT,
    model_answer TEXT,
    UNIQUE(part, topic, question)
);

CREATE TABLE IF NOT EXISTS speaking_sessions (
    id INTEGER PRIMARY KEY,
    mock_id INTEGER REFERENCES mock_exams(id) ON DELETE SET NULL,
    created_at TEXT,
    finished_at TEXT,
    plan_json TEXT,
    mode TEXT
);

CREATE TABLE IF NOT EXISTS speaking_responses (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES speaking_sessions(id) ON DELETE CASCADE,
    question_id INTEGER REFERENCES speaking_questions(id) ON DELETE SET NULL,
    part INTEGER,
    question_text TEXT,
    audio_path TEXT,
    duration_sec REAL,
    mime TEXT,
    transcript TEXT,
    browser_transcript TEXT,
    whisper_json TEXT,
    metrics_json TEXT,
    transcribe_status TEXT,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_speaking_responses_session ON speaking_responses(session_id);

CREATE TABLE IF NOT EXISTS ai_analyses (
    id INTEGER PRIMARY KEY,
    target_type TEXT NOT NULL,
    target_id INTEGER NOT NULL,
    provider TEXT,
    status TEXT DEFAULT 'queued',
    prompt TEXT,
    result_md TEXT,
    result_json TEXT,
    error TEXT,
    log_path TEXT,
    created_at TEXT,
    started_at TEXT,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_ai_analyses_target ON ai_analyses(target_type, target_id);

CREATE TABLE IF NOT EXISTS kb_docs (
    id INTEGER PRIMARY KEY,
    slug TEXT UNIQUE,
    title TEXT,
    category TEXT,
    tags TEXT,
    path TEXT,
    content_md TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS kb_fts USING fts5(
    title, content_md, content='kb_docs', content_rowid='id', tokenize='porter unicode61'
);

CREATE TABLE IF NOT EXISTS vocab (
    id INTEGER PRIMARY KEY,
    term TEXT NOT NULL,
    meaning TEXT,
    example TEXT,
    topic TEXT NOT NULL DEFAULT '',
    source TEXT,
    ease REAL DEFAULT 2.5,
    interval_days INTEGER DEFAULT 0,
    due_at TEXT,
    reps INTEGER DEFAULT 0,
    UNIQUE(term, topic)
);

-- Results achieved outside the app (score screenshots, trial exams). is_mine = the learner (matched via the user_name setting).
CREATE TABLE IF NOT EXISTS external_results (
    id INTEGER PRIMARY KEY,
    date TEXT,
    person TEXT NOT NULL,
    is_mine INTEGER DEFAULT 0,
    listening REAL,
    reading REAL,
    writing REAL,
    speaking REAL,
    overall REAL,
    notes TEXT,
    photo TEXT,
    source TEXT,
    UNIQUE(date, person, photo)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
