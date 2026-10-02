/**
 * A served-content table: columns declare their own cells, numeric columns align
 * right with tabular numerals. The scroll region is focusable (keyboard users can
 * reach wide tables) and labelled by the table's caption.
 */
export function DataTable({ caption, columns, rows, getKey, empty, minWidth = 640 }) {
  return (
    <div className="table-scroll" tabIndex={0} role="region" aria-label={caption}>
      <table className="table" style={{ minWidth }}>
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} scope="col" className={c.num ? 'table__th table__th--num' : 'table__th'}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td className="table__empty" colSpan={columns.length}>{empty || '—'}</td>
            </tr>
          ) : rows.map((row, i) => (
            <tr key={getKey ? getKey(row, i) : i}>
              {columns.map((c) => (
                <td key={c.key} className={c.num ? 'table__td table__td--num' : 'table__td'}>
                  {c.render ? c.render(row) : row[c.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
