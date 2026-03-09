-- The Vault Schema (MySQL Compatible)
CREATE DATABASE IF NOT EXISTS telemetry_db;
USE telemetry_db;

-- Stores Sessions, Users, and Events

CREATE TABLE IF NOT EXISTS player (
    player_id INT PRIMARY KEY AUTO_INCREMENT,
    username VARCHAR(50) UNIQUE NOT NULL,
    password VARCHAR(100) NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS savefile (
    save_id INT PRIMARY KEY AUTO_INCREMENT,
    player_id INT,
    slot_number INT,
    completion_pct DECIMAL(5,2),
    last_updated TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (player_id)
    REFERENCES player(player_id)
);

CREATE TABLE IF NOT EXISTS mapzone (
    area_code INT PRIMARY KEY,
    area_name VARCHAR(100) NOT NULL,
    x_min DECIMAL(10,2) NOT NULL,
    y_min DECIMAL(10,2) NOT NULL,
    x_max DECIMAL(10,2) NOT NULL,
    y_max DECIMAL(10,2) NOT NULL
);

CREATE TABLE IF NOT EXISTS playersession (
    session_id INT PRIMARY KEY AUTO_INCREMENT,
    player_id INT,
    save_id INT,
    start_time DATETIME NOT NULL,
    end_time DATETIME,

    FOREIGN KEY (player_id)
    REFERENCES player(player_id),

    FOREIGN KEY (save_id)
    REFERENCES savefile(save_id)
);

CREATE TABLE IF NOT EXISTS deathevent (
    death_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    session_id INT,
    area_code INT,
    death_x DECIMAL(10,2) NOT NULL,
    death_y DECIMAL(10,2) NOT NULL,
    death_cause VARCHAR(80) NOT NULL,

    FOREIGN KEY (session_id)
    REFERENCES playersession(session_id),

    FOREIGN KEY (area_code)
    REFERENCES mapzone(area_code)
);

CREATE TABLE IF NOT EXISTS playerevent (
    event_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    session_id INT NOT NULL,
    area_code INT,
    event_type VARCHAR(50) NOT NULL,
    event_x DECIMAL(10,2),
    event_y DECIMAL(10,2),
    event_value INT,
    event_time DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (session_id)
    REFERENCES playersession(session_id),

    FOREIGN KEY (area_code)
    REFERENCES mapzone(area_code)
);

CREATE INDEX idx_session_death ON deathevent(session_id);
CREATE INDEX idx_area_death ON deathevent(area_code);
CREATE INDEX idx_session_event ON playerevent(session_id);
CREATE INDEX idx_area_event ON playerevent(area_code);
CREATE INDEX idx_event_type ON playerevent(event_type);

