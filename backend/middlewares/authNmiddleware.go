package middlewares

import (
	"Backend/errors"
	"log/slog"
	"net/http"
	"strings"
)

func AuthNMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// extract the token from the request headers
		authzToken := r.Header.Get("Authorization")

		if authzToken == "" {
			slog.Debug(
				"Invalid Request, auth token not present",
			)

			errJson, badRequestError := errors.NewBadRequestError("Invalid Request, auth token not present", nil)
			w.WriteHeader(badRequestError.Code)
			w.Write(errJson)

			return
		}

		// take out the role from the context
		ctx := r.Context()
		userRole := ctx.Value("role").(string)

		// check the request if its an admin request (/admin in the path)
		requestPath := r.URL.Path
		isAdminRequest := strings.HasPrefix(requestPath, "/admin")

		if isAdminRequest && userRole != "admin" {
			slog.Debug(
				"Unauthorized access attempt to the admin endpoint",
				slog.Any("Role", userRole),
				slog.String("Path", requestPath),
			)

			errJson, unauthorizedError := errors.NewUnauthorizedError(
				"Insufficient permissions to access the resource", nil,
			)

			w.WriteHeader(unauthorizedError.Code)
			w.Write(errJson)
			return
		}

		slog.Info("Successfully Authenticated the User with the right role!", slog.String("Role", userRole))

		next.ServeHTTP(w, r)
	})
}
