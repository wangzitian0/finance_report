---
applyTo: "**/*.{ts,tsx}"
---

# TypeScript/Next.js Development Instructions

## Framework
- Next.js 14 with App Router
- React 18 with Server Components
- TypeScript 5 strict mode
- shadcn/ui + TailwindCSS

## Component Patterns

### Server Components (Default)
```tsx
// app/accounts/page.tsx
import { getAccounts } from '@/lib/api'

export default async function AccountsPage() {
  const accounts = await getAccounts()
  return <AccountList accounts={accounts} />
}
```

### Client Components (When Needed)
```tsx
'use client'

import { useState } from 'react'

export function AccountForm() {
  const [name, setName] = useState('')
  // Interactive logic here
}
```

## Type Safety

### No `any` Types
```typescript
// ✅ Correct
interface Account {
  id: string
  name: string
  type: 'ASSET' | 'LIABILITY' | 'EQUITY' | 'INCOME' | 'EXPENSE'
  balance: string // Decimal as string from API
}

// ❌ Wrong
const account: any = response.data
```

### API Response Types
```typescript
import { z } from 'zod'

const AccountSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  type: z.enum(['ASSET', 'LIABILITY', 'EQUITY', 'INCOME', 'EXPENSE']),
  balance: z.string(),
})

type Account = z.infer<typeof AccountSchema>
```

## Data Fetching

### TanStack Query
```typescript
import { useQuery, useMutation } from '@tanstack/react-query'

export function useAccounts() {
  return useQuery({
    queryKey: ['accounts'],
    queryFn: () => api.get<Account[]>('/accounts'),
  })
}

export function useCreateAccount() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: CreateAccountInput) => api.post('/accounts', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['accounts'] })
    },
  })
}
```

## UI Components

### shadcn/ui Usage
```tsx
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
```

### Form Handling
```tsx
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'

export function AccountForm() {
  const form = useForm<CreateAccountInput>({
    resolver: zodResolver(CreateAccountSchema),
  })
  // ...
}
```

## Monetary Display

### Format Currency
```typescript
const formatCurrency = (amount: string, currency: string) => {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
  }).format(parseFloat(amount))
}
```

## Accessibility
- Use semantic HTML elements
- Include aria-labels for icons
- Ensure keyboard navigation
- Support screen readers
