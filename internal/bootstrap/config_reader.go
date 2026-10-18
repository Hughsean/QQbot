package bootstrap

import (
	"fmt"
	"strconv"
)

type configReader struct {
	values map[string]string
	err    error
}

func (r *configReader) text(key, fallback string) string {
	if v, ok := r.values[key]; ok {
		return v
	}
	return fallback
}

func (r *configReader) integer(key string, fallback, min, max int) int {
	value, exists := r.values[key]
	if !exists {
		return fallback
	}
	n, err := strconv.Atoi(value)
	if err != nil || n < min || n > max {
		r.err = fmt.Errorf("%s must be an integer in [%d,%d]", key, min, max)
		return fallback
	}
	return n
}

func (r *configReader) boolean(key string, fallback bool) bool {
	v, exists := r.values[key]
	if !exists {
		return fallback
	}
	b, err := strconv.ParseBool(v)
	if err != nil {
		r.err = fmt.Errorf("%s must be a boolean", key)
	}
	return b
}
