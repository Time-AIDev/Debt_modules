import { useEffect, useRef, useState } from 'react'
import { usePrefs } from '../lib/prefs.jsx'
import { useCaseDetail } from '../lib/useCaseDetail.js'
import { RecordView, businessDateOf } from './RecordView.jsx'
import { ContactDrawer, contactSummary, openPromise } from './ContactDrawer.jsx'
import { useContentBox, useDialogFocus } from './Drawer.jsx'

/** The case itself, loaded fresh for each customer the sheet opens on. */
function SheetCase({ uid, item, openLog, onLogClose, onClose, onChanged }) {
  const { data, problem, load } = useCaseDetail(uid)
  const [contactOpen, setContactOpen] = useState(!!openLog)
  // "บันทึกผลการติดต่อ" on a board card / NPL row opens the sheet with its contact drawer.
  useEffect(() => { if (openLog) setContactOpen(true) }, [openLog])
  const closeContact = () => { setContactOpen(false); onLogClose?.() }
  const saved = () => { load(); onChanged?.() }
  return (
    <>
      <div className="casesheet__body">
        <RecordView
          mode="sheet"
          item={item}
          onClose={onClose}
          data={data}
          problem={problem}
          onRetry={load}
          onChanged={saved}
          onLogContact={() => setContactOpen(true)}
        />
      </div>
      <ContactDrawer
        open={contactOpen && !!data}
        onClose={closeContact}
        customer={data?.customer}
        businessDate={businessDateOf(data)}
        summary={contactSummary(data)}
        promise={openPromise(data)}
        onSaved={saved}
      />
    </>
  )
}

/**
 * The customer case as a pop-up sheet (design D) — opened from the Today board and
 * from NPL: a scrim over the content column, the case at its right (796 wide, 20 from
 * the edges). Esc and the scrim close it; focus goes in on open and back on close. The
 * case's own drawers open inside the sheet. `onChanged` runs after every save. `item` is
 * the served Today row when there is one (tier, worked stamp); `openLog` opens the sheet
 * with its contact drawer, and `onLogClose` tells the caller that drawer closed.
 */
export function CaseSheet({ uid, open, onClose, onChanged, item, openLog, onLogClose }) {
  const { t } = usePrefs()
  const dialogRef = useRef(null)
  const rootRef = useRef(null)
  useDialogFocus(open, dialogRef, onClose)
  const box = useContentBox(open, rootRef)

  if (!open) return null
  return (
    <div className="casesheet" style={box} ref={rootRef}>
      <div className="casesheet__scrim" onClick={onClose} />
      <div className="casesheet__dialog" role="dialog" aria-modal="true" aria-label={t('shell.caseSheet')}
           ref={dialogRef} tabIndex={-1}>
        <SheetCase key={uid} uid={uid} item={item} openLog={openLog} onLogClose={onLogClose}
                   onClose={onClose} onChanged={onChanged} />
      </div>
    </div>
  )
}
