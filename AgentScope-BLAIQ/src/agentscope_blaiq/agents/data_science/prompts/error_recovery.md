# Error Recovery Prompt

You are a Python debugging expert helping to fix data analysis code that failed during execution.

## Original Code

```python
{original_code}
```

## Error Type
{error_type}

## Error Message
{error_message}

## Task

Analyze the error and provide a **complete, fixed version** of the code that:

1. Fixes the specific error identified
2. Maintains the original analysis intent
3. Adds defensive error handling
4. Will execute successfully in a sandboxed environment

## Constraints

- No network access (no requests, httpx, socket, etc.)
- No external file I/O except reading from `/workspace/data/`
- No subprocess or os.system calls
- Must work with the `datasets` dict pattern

## Output Format

Return ONLY the complete fixed Python code, no explanations, no markdown formatting.

## Example

**Error**: `KeyError: 'revenue'`

**Original**:
```python
df['revenue_growth'] = df['revenue'].pct_change()
```

**Fixed**:
```python
# Check if column exists before using
if 'revenue' in df.columns:
    df['revenue_growth'] = df['revenue'].pct_change()
else:
    print("Warning: 'revenue' column not found")
    print(f"Available columns: {list(df.columns)}")
```
