import { useMemo } from 'react'
import { usePrefs } from '../../lib/prefs.jsx'
import { StatusIcon } from '../StatusIcon.jsx'

const joined = (values) => (values || []).filter(Boolean).join(', ')

/** Header-only PEAK contract and parser feedback. It never renders workbook rows. */
export function SchemaFeedback({ contract, diagnostics }) {
  const { t } = usePrefs()
  const headings = useMemo(() => new Map(
    [...(contract?.required || []), ...(contract?.optional || [])]
      .map((field) => [field.field, field.heading]),
  ), [contract])
  if (!contract) return null

  const names = (fields) => joined((fields || []).map((field) => headings.get(field) || field))
  const missingRequired = names(diagnostics?.missing_required_fields)
  const missingOptional = names(diagnostics?.missing_optional_fields)
  const ignored = joined(diagnostics?.ignored_headings)
  const duplicateItems = Array.isArray(diagnostics?.duplicate_headings)
    ? diagnostics.duplicate_headings
    : Object.entries(diagnostics?.duplicate_headings || {}).map(([heading, columns]) => ({ heading, columns }))
  const duplicates = joined(duplicateItems.map((item) => (
    typeof item === 'string' ? item : `${item.heading} (${joined(item.columns)})`
  )))
  const hasFeedback = missingRequired || missingOptional || ignored || duplicates

  return (
    <section className="imp-schema" aria-label={t('peak.schemaTitle')}>
      <div className="imp-schema__head">
        <StatusIcon kind={missingRequired ? 'problem' : 'idle'} size={14} />
        <strong>{t('peak.schemaRequired')}</strong>
      </div>
      <ul className="imp-schema__fields">
        {(contract.required || []).map((field) => (
          <li key={field.field}>
            <code>{field.heading}</code>
            {field.aliases?.length ? <span>{t('peak.schemaAliases', { aliases: joined(field.aliases) })}</span> : null}
          </li>
        ))}
      </ul>
      {(contract.optional || []).length ? (
        <details className="imp-schema__optional">
          <summary>{t('peak.schemaOptional', { n: contract.optional.length })}</summary>
          <p>{joined(contract.optional.map((field) => field.heading))}</p>
        </details>
      ) : null}
      {hasFeedback ? (
        <div className={`imp-schema__feedback${missingRequired ? ' imp-schema__feedback--problem' : ''}`} role="status">
          {missingRequired ? <p>{t('peak.schemaMissingRequired', { fields: missingRequired })}</p> : null}
          {missingOptional ? <p>{t('peak.schemaMissingOptional', { fields: missingOptional })}</p> : null}
          {ignored ? <p>{t('peak.schemaIgnored', { fields: ignored })}</p> : null}
          {duplicates ? <p>{t('peak.schemaDuplicates', { fields: duplicates })}</p> : null}
          {missingRequired ? <p>{t('peak.schemaFix')}</p> : null}
        </div>
      ) : null}
    </section>
  )
}
