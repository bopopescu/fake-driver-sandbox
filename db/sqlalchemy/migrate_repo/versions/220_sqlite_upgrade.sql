BEGIN TRANSACTION;
    /* Resorting to SQL for sqlite upgrade, sqlite doesn't allow column alter, so create new table and copy from old */
    ALTER TABLE compute_nodes_pf9_ip_info RENAME TO tmp_compute_nodes_pf9_ip_info;
    CREATE TABLE compute_nodes_pf9_ip_info (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted INTEGER,
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        host_id INTEGER,
        interface_name VARCHAR(128),
        ip VARCHAR(128)
    );

    INSERT INTO compute_nodes_pf9_ip_info(created_at, updated_at, deleted_at, deleted, id, host_id, interface_name, ip)
    SELECT created_at, updated_at, deleted_at, deleted, id, host_id, interface_name, ip
    FROM tmp_compute_nodes_pf9_ip_info;
    DROP TABLE tmp_compute_nodes_pf9_ip_info;

    ALTER TABLE compute_nodes_pf9_ext RENAME TO tmp_compute_nodes_pf9_ext;
    CREATE TABLE compute_nodes_pf9_ext (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted INTEGER,
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        host_id INTEGER,
        host_name VARCHAR(128)
    );

    INSERT INTO compute_nodes_pf9_ext(created_at, updated_at, deleted_at, deleted, id, host_id, host_name)
    SELECT created_at, updated_at, deleted_at, deleted, id, host_id, host_name
    FROM tmp_compute_nodes_pf9_ext;

    DROP TABLE tmp_compute_nodes_pf9_ext;

    ALTER TABLE compute_nodes_pf9_stats RENAME TO tmp_compute_nodes_pf9_stats;
    CREATE TABLE compute_nodes_pf9_stats (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted INTEGER,
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        host_id INTEGER,
        key VARCHAR(128),
        value VARCHAR(256)
    );

    INSERT INTO compute_nodes_pf9_stats(created_at, updated_at, deleted_at, deleted, id, host_id, key, value)
    SELECT created_at, updated_at, deleted_at, deleted, id, host_id, key, value
    FROM tmp_compute_nodes_pf9_stats;

    DROP TABLE tmp_compute_nodes_pf9_stats;

    ALTER TABLE shadow_compute_nodes_pf9_ip_info RENAME TO tmp_shadow_compute_nodes_pf9_ip_info;
    CREATE TABLE shadow_compute_nodes_pf9_ip_info (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted INTEGER,
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        host_id INTEGER,
        interface_name VARCHAR(128),
        ip VARCHAR(128)
    );

    INSERT INTO shadow_compute_nodes_pf9_ip_info(created_at, updated_at, deleted_at, deleted, id, host_id, interface_name, ip)
    SELECT created_at, updated_at, deleted_at, deleted, id, host_id, interface_name, ip
    FROM tmp_shadow_compute_nodes_pf9_ip_info;

    DROP TABLE tmp_shadow_compute_nodes_pf9_ip_info;

    ALTER TABLE shadow_compute_nodes_pf9_ext RENAME TO tmp_shadow_compute_nodes_pf9_ext;
    CREATE TABLE shadow_compute_nodes_pf9_ext (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted INTEGER,
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        host_id INTEGER,
        host_name VARCHAR(128)
    );

    INSERT INTO shadow_compute_nodes_pf9_ext(created_at, updated_at, deleted_at, deleted, id, host_id, host_name)
    SELECT created_at, updated_at, deleted_at, deleted, id, host_id, host_name
    FROM tmp_shadow_compute_nodes_pf9_ext;

    DROP TABLE tmp_shadow_compute_nodes_pf9_ext;

    ALTER TABLE shadow_compute_nodes_pf9_stats RENAME TO tmp_shadow_compute_nodes_pf9_stats;
    CREATE TABLE shadow_compute_nodes_pf9_stats (
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        deleted INTEGER,
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        host_id INTEGER,
        key VARCHAR(128),
        value VARCHAR(256)
    );

    INSERT INTO shadow_compute_nodes_pf9_stats(created_at, updated_at, deleted_at, deleted, id, host_id, key, value)
    SELECT created_at, updated_at, deleted_at, deleted, id, host_id, key, value
    FROM tmp_shadow_compute_nodes_pf9_stats;

    DROP TABLE tmp_shadow_compute_nodes_pf9_stats;

COMMIT;