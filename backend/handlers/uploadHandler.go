package handlers

import (
	"Backend/errors"
	"Backend/services"
	"log/slog"
	"net/http"
)

type UploadHandler struct {
	Service *services.UploadService
}

func (s *UploadHandler) HandleReceiptUploads(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		w.WriteHeader(http.StatusMethodNotAllowed)
		w.Write([]byte(`{"error": "Only POST method allowed"}`))
		return
	}

	// parse as multipart form (max 10 MB)
	err := r.ParseMultipartForm(10 << 20)
	if err != nil {
		slog.Warn("Failed to parse multipart form")
		errorJson, badRequestError := errors.NewBadRequestError("Error parsing multipart form, file too large or bad request", err)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(badRequestError.Code)
		w.Write(errorJson)
		return
	}

	// read form fields
	currency := r.FormValue("currency")
	if currency == "" {
		slog.Warn("Missing required field: currency")
		errorJson, badRequestError := errors.NewBadRequestError("Missing required field: currency", nil)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(badRequestError.Code)
		w.Write(errorJson)
		return
	}

	// extract the image file
	file, header, err := r.FormFile("image")
	if err != nil {
		slog.Error("Failed to extract uploaded image from form")
		errorJson, badRequestError := errors.NewBadRequestError("Error extracting uploaded receipt image", err)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(badRequestError.Code)
		w.Write(errorJson)
		return
	}
	defer file.Close()

	userID := r.Context().Value("userID").(string)
	email := r.Context().Value("email").(string)

	slog.Info("Receipt upload request received",
		slog.String("UserID", userID),
		slog.String("Currency", currency),
		slog.String("Filename", header.Filename),
		slog.Int64("FileSize", header.Size),
	)

	responseData, err, errCode, errJsonData := s.Service.ProcessReceiptImage(file, currency, userID, email)

	if err != nil {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(errCode)
		w.Write(errJsonData)
		slog.Error("Receipt upload failed",
			slog.String("UserID", userID),
			slog.Int("StatusCode", errCode),
		)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	w.Write(responseData)

	slog.Info("Receipt uploaded successfully", slog.String("UserID", userID))
}
