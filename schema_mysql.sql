-- Schéma MySQL pour la base courses Kotcha
CREATE DATABASE IF NOT EXISTS kotcha_races CHARACTER SET utf8mb4;
USE kotcha_races;

CREATE TABLE IF NOT EXISTS races (
        id           BIGINT       NOT NULL AUTO_INCREMENT,
        source       VARCHAR(64)  NOT NULL,
        external_id  VARCHAR(128) NOT NULL,
        nom          TEXT         NULL,
        url          VARCHAR(1024) NULL,
        date         DATE         NULL,
        pays         VARCHAR(8)   NULL,
        ville        VARCHAR(255) NULL,
        distance_km  DOUBLE       NULL,
        type         VARCHAR(16)  NULL,
        prix         DECIMAL(10,2) NULL,
        devise       VARCHAR(8)   NULL,
        updated_at   DATETIME     NULL,
        PRIMARY KEY (id),
        UNIQUE KEY uq_source_external (source, external_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
