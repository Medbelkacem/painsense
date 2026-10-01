import React from 'react';
import { cx } from '../lib/cx';

export interface Column<Row> {
  key: string;
  header: React.ReactNode;
  /** Right-align numeric columns; the header follows the cell. */
  align?: 'left' | 'right';
  width?: string;
  /** Columns that drop out first on a narrow screen. */
  hideBelow?: 'sm' | 'md' | 'lg';
  cell: (row: Row) => React.ReactNode;
}

const hideClass = {
  sm: 'hidden sm:table-cell',
  md: 'hidden md:table-cell',
  lg: 'hidden lg:table-cell',
} as const;

interface DataTableProps<Row> {
  columns: readonly Column<Row>[];
  rows: readonly Row[];
  rowKey: (row: Row) => string;
  onRowClick?: (row: Row) => void;
  empty?: React.ReactNode;
}

export function DataTable<Row>({
  columns,
  rows,
  rowKey,
  onRowClick,
  empty,
}: DataTableProps<Row>) {
  if (rows.length === 0 && empty) return <>{empty}</>;

  return (
    <div className="-mx-1 overflow-x-auto px-1">
      <table className="w-full border-collapse text-[13px]">
        <thead>
          <tr className="border-b border-hairline">
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                style={column.width ? { width: column.width } : undefined}
                className={cx(
                  'px-3 pb-2 text-left text-[11px] font-medium whitespace-nowrap text-faint',
                  column.align === 'right' && 'text-right',
                  column.hideBelow && hideClass[column.hideBelow],
                )}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={rowKey(row)}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              tabIndex={onRowClick ? 0 : undefined}
              onKeyDown={
                onRowClick
                  ? (event) => {
                      if (event.key === 'Enter') onRowClick(row);
                    }
                  : undefined
              }
              className={cx(
                'border-b border-hairline/70 transition-colors last:border-0',
                onRowClick && 'cursor-pointer hover:bg-sunken',
              )}
            >
              {columns.map((column) => (
                <td
                  key={column.key}
                  className={cx(
                    'px-3 py-2.5 align-middle',
                    column.align === 'right' && 'text-right',
                    column.hideBelow && hideClass[column.hideBelow],
                  )}
                >
                  {column.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
