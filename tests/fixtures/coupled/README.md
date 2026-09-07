`products.xls` is a real Excel BIFF8 workbook generated with xlwt 1.3.0 for the
legacy Excel reader regression. It contains a `Products` sheet with the columns
`sample, product, product_moles, n, charge` and two synthetic rows:

| sample | product | product_moles (mol) | n | charge (C) |
| --- | --- | --- | --- | --- |
| sample-a | H2 | 0.000002 | 2 | 1.0 |
| sample-a | CO | 0.000001 | 2 | 1.0 |

The expected hydrogen FE is 38.594132848% and its mole selectivity is 2/3.
xlwt is only the fixture generator; normal tests and the application need xlrd
to read the checked-in workbook. No instrument or user data are included.
