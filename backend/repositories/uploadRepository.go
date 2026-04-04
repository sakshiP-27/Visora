package repositories

import (
	"Backend/models"
	"context"
	"fmt"
	"log/slog"

	"github.com/jackc/pgx/v5/pgxpool"
)

type UploadRepository struct {
	DB *pgxpool.Pool
}

func NewUploadRepository(db *pgxpool.Pool) *UploadRepository {
	return &UploadRepository{DB: db}
}

// StoreReceipt inserts the receipt and its items in a single transaction.
func (repo *UploadRepository) StoreReceipt(userID string, receipt models.GenAIUploadResponse, imageURL string) (string, error) {
	tx, err := repo.DB.Begin(context.Background())
	if err != nil {
		return "", fmt.Errorf("failed to begin transaction: %w", err)
	}
	defer tx.Rollback(context.Background()) // no-op if already committed

	// insert receipt and get back the generated UUID
	receiptQuery := `
		INSERT INTO receipts (user_id, merchant, date, total_amount, currency, confidence_score, image_url, image_hash, source)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'scan')
		RETURNING id`

	var receiptID string
	err = tx.QueryRow(context.Background(), receiptQuery,
		userID,
		receipt.Merchant,
		receipt.Date,
		receipt.TotalAmount,
		receipt.Currency,
		receipt.ConfidenceScore,
		imageURL,
		receipt.ImageHash,
	).Scan(&receiptID)

	if err != nil {
		return "", fmt.Errorf("failed to insert receipt: %w", err)
	}

	// insert each item, looking up category_id by name
	itemQuery := `
		INSERT INTO items (receipt_id, name, price, category_id, quantity)
		VALUES ($1, $2, $3, (SELECT id FROM categories WHERE name = $4), $5)`

	for _, item := range receipt.Items {
		_, err = tx.Exec(context.Background(), itemQuery,
			receiptID,
			item.Name,
			item.Price,
			item.Category,
			item.Quantity,
		)
		if err != nil {
			return "", fmt.Errorf("failed to insert item %s: %w", item.Name, err)
		}
	}

	// commit the transaction
	err = tx.Commit(context.Background())
	if err != nil {
		return "", fmt.Errorf("failed to commit transaction: %w", err)
	}

	slog.Info("Receipt stored in DB",
		slog.String("ReceiptID", receiptID),
		slog.String("UserID", userID),
		slog.Int("ItemCount", len(receipt.Items)),
	)

	return receiptID, nil
}

// StoreManualExpense inserts a manually entered expense and its items in a single transaction.
func (repo *UploadRepository) StoreManualExpense(userID string, expense models.ManualExpenseRequest, totalAmount float64) (string, error) {
	tx, err := repo.DB.Begin(context.Background())
	if err != nil {
		return "", fmt.Errorf("failed to begin transaction: %w", err)
	}
	defer tx.Rollback(context.Background())

	receiptQuery := `
		INSERT INTO receipts (user_id, merchant, date, total_amount, currency, confidence_score, image_url, source)
		VALUES ($1, $2, $3, $4, $5, 1.0, '', 'manual')
		RETURNING id`

	var receiptID string
	err = tx.QueryRow(context.Background(), receiptQuery,
		userID,
		expense.Merchant,
		expense.Date,
		totalAmount,
		expense.Currency,
	).Scan(&receiptID)

	if err != nil {
		return "", fmt.Errorf("failed to insert manual expense: %w", err)
	}

	itemQuery := `
		INSERT INTO items (receipt_id, name, price, category_id, quantity)
		VALUES ($1, $2, $3, (SELECT id FROM categories WHERE name = $4), $5)`

	for _, item := range expense.Items {
		_, err = tx.Exec(context.Background(), itemQuery,
			receiptID,
			item.Name,
			item.Price,
			item.Category,
			item.Quantity,
		)
		if err != nil {
			return "", fmt.Errorf("failed to insert item %s: %w", item.Name, err)
		}
	}

	err = tx.Commit(context.Background())
	if err != nil {
		return "", fmt.Errorf("failed to commit transaction: %w", err)
	}

	slog.Info("Manual expense stored in DB",
		slog.String("ReceiptID", receiptID),
		slog.String("UserID", userID),
		slog.Int("ItemCount", len(expense.Items)),
	)

	return receiptID, nil
}

func (repo *UploadRepository) GetReceiptOnImageHash(userID string, imageHash string) (*models.StoredReceipt, error) {
	receiptQuery := `
		SELECT id, merchant, date, total_amount, currency, confidence_score
		FROM receipts
		WHERE image_hash = $1 AND user_id = $2
		LIMIT 1`

	var receiptID, merchant, date, currency string
	var totalAmount, confidenceScore float64

	err := repo.DB.QueryRow(context.Background(), receiptQuery, imageHash, userID).Scan(
		&receiptID, &merchant, &date, &totalAmount, &currency, &confidenceScore,
	)

	if err != nil {
		return nil, nil
	}

	itemsQuery := `
		SELECT i.name, i.price, i.quantity, c.name AS category
		FROM items i
		JOIN categories c ON c.id = i.category_id
		WHERE i.receipt_id = $1`

	rows, err := repo.DB.Query(context.Background(), itemsQuery, receiptID)
	if err != nil {
		return nil, fmt.Errorf("failed to fetch items for duplicate receipt: %w", err)
	}
	defer rows.Close()

	var items []models.ReceiptItems
	for rows.Next() {
		var item models.ReceiptItems
		if err := rows.Scan(&item.Name, &item.Price, &item.Quantity, &item.Category); err != nil {
			return nil, fmt.Errorf("failed to scan item row: %w", err)
		}
		items = append(items, item)
	}

	return &models.StoredReceipt{
		ReceiptID:       receiptID,
		Merchant:        merchant,
		Date:            date,
		TotalAmount:     totalAmount,
		Currency:        currency,
		ConfidenceScore: confidenceScore,
		Items:           items,
	}, nil
}
