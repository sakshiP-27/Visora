package db

import (
	"context"
	"embed"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

//go:embed migrations/*.sql
var migrationFiles embed.FS

var Pool *pgxpool.Pool

func Connect(connectionString string) error {
	maxRetries := 10
	baseDelay := 5 * time.Second
	maxDelay := 2 * time.Minute

	var pool *pgxpool.Pool
	var err error

	for attempt := 1; attempt <= maxRetries; attempt++ {
		pool, err = pgxpool.New(context.Background(), connectionString)
		if err != nil {
			slog.Warn("Failed to create database pool",
				slog.Int("Attempt", attempt),
				slog.Int("MaxRetries", maxRetries),
				slog.Any("Error", err),
			)
		} else {
			// Verify connection with a ping
			err = pool.Ping(context.Background())
			if err == nil {
				Pool = pool
				slog.Info("Connected to PostgreSQL database",
					slog.Int("AttemptsNeeded", attempt),
				)
				return nil
			}
			// Ping failed, close the pool before retrying
			pool.Close()
			slog.Warn("Database ping failed",
				slog.Int("Attempt", attempt),
				slog.Int("MaxRetries", maxRetries),
				slog.Any("Error", err),
			)
		}

		if attempt == maxRetries {
			break
		}

		// Exponential backoff: 5s, 10s, 20s, 40s, 80s, 120s, 120s...
		delay := baseDelay * time.Duration(1<<(attempt-1))
		if delay > maxDelay {
			delay = maxDelay
		}

		slog.Info("Retrying database connection...",
			slog.String("NextAttemptIn", delay.String()),
		)
		time.Sleep(delay)
	}

	return fmt.Errorf("unable to connect to database after %d attempts: %w", maxRetries, err)
}

func RunMigrations() error {
	files := []string{
		"migrations/001_init_schema.sql",
		"migrations/002_seed_categories.sql",
		"migrations/003_add_analytics_insights.sql",
		"migrations/004_add_entry_source.sql",
		"migrations/005_seed_new_categories.sql",
		"migrations/006_add_user_name.sql",
		"migrations/007_add_image_hash.sql",
	}

	for _, file := range files {
		content, err := migrationFiles.ReadFile(file)
		if err != nil {
			return fmt.Errorf("failed to read migration %s: %w", file, err)
		}

		sql := strings.TrimSpace(string(content))
		if sql == "" {
			continue
		}

		_, err = Pool.Exec(context.Background(), sql)
		if err != nil {
			return fmt.Errorf("failed to run migration %s: %w", file, err)
		}

		slog.Info("Migration applied", slog.String("file", file))
	}

	return nil
}

func Close() {
	if Pool != nil {
		Pool.Close()
		slog.Info("Database connection closed")
	}
}
