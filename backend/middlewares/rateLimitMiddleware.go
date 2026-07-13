package middlewares

import (
	"net/http"
	"time"

	"github.com/go-chi/httprate"
)

func RateLimitMiddleware(requestLimit int, windowLength time.Duration) func(http.Handler) http.Handler {
	return httprate.Limit(
		requestLimit,
		windowLength,
		httprate.WithKeyFuncs(func(r *http.Request) (string, error) {
			// extract userID from the context
			userID := r.Context().Value("userID")
			if userID == nil {
				// if no userID then fallback to IP
				return httprate.KeyByIP(r)
			}
			return userID.(string), nil
		}),
		httprate.WithLimitHandler(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusTooManyRequests)
			w.Write([]byte(`{ "error": "Rate Limit Exceeded. Please try again later!" }`))
		})),
	)
}
