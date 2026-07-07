# codag (Go)

Go client for the Codag hosted API. This is the package documentation rendered
on [pkg.go.dev](https://pkg.go.dev/github.com/codag-megalith/codag-sdk/go).

```bash
go get github.com/codag-megalith/codag-sdk/go
```

```go
package main

import (
	"context"
	"fmt"
	"log"

	codag "github.com/codag-megalith/codag-sdk/go"
)

func main() {
	// Reads CODAG_API_KEY and CODAG_SERVER from the environment.
	// Override with codag.WithAPIKey(...) / codag.WithBaseURL(...).
	client := codag.New()

	result, err := client.Compact(context.Background(), []string{
		"ERROR api db pool timeout active=20 waiting=30 path=/api/orders",
	}, nil)
	if err != nil {
		log.Fatal(err)
	}
	fmt.Println(result.Text)
	fmt.Println(result.Stats.ElapsedMS)
}
```

## Input shapes

`Compact`, `Capsule`, and `CreateCompactJob` accept either `[]string` or
`[]codag.LineRecord` as their `lines` argument. Use `RequestOptions` to set a
default `Service`, `Level`, or `Metadata`.

## Errors

Non-2xx responses return an `*APIError`. Use `errors.Is` against the sentinels
to branch on the common cases:

```go
_, err := client.Capsule(ctx, lines, nil)
switch {
case errors.Is(err, codag.ErrAuthentication): // 401
case errors.Is(err, codag.ErrBilling):         // 402, see APIError.UpgradePath
case errors.Is(err, codag.ErrRateLimited):     // 429, see APIError.RetryAfter
}
```

See the repository root README for the full multi-language SDK documentation.
