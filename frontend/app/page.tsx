'use client'

import { useState, useEffect, FormEvent } from 'react'

// ── Types ─────────────────────────────────────────────────────────────────────

interface CPTCandidate {
  cpt_code: string
  label: string
  confidence: number
}

interface QualitySignals {
  cms_outcome_rating?: number
  procedure_volume?: number
  patient_satisfaction?: number
}

interface TimelinePoint {
  months: number
  label: string
  date: string | null
  cumulative_medical_oop: number
  cumulative_premiums: number
  cumulative_hsa_credits: number
  net_out_of_pocket: number
  deductible_remaining: number
  oop_max_remaining: number
  payment_plan_balance_remaining: number
}

interface Timeline {
  procedure_oop: number
  payment_plan_monthly: number
  timeline_points: TimelinePoint[]
}

interface Provider {
  npi: string
  provider_name: string
  specialty: string
  address: string
  city: string
  state: string
  zip: string
  distance_miles: number
  cpt_code: string
  negotiated_rate: number
  estimated_oop: number
  quality_score: number | null
  quality_signals: QualitySignals
  rank: number
  ranking_basis: string
  notes: string[]
  timeline?: Timeline
}

interface SearchResults {
  status: string
  ranking_basis: string
  result_count: number
  results: Provider[]
  warnings: string[]
  disclaimer: string
  meta: { latency_ms: number; total_providers_evaluated: number }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatOOP(amount: number): string {
  if (amount === 0) return '$0'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(amount)
}

function formatRate(amount: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(amount)
}

function oopColorClass(oop: number, allProviders: Provider[]): string {
  const oops = allProviders.map((p) => p.estimated_oop)
  const min = Math.min(...oops)
  const max = Math.max(...oops)
  if (max === min) return 'text-emerald-400'
  const pct = (oop - min) / (max - min)
  if (pct < 0.33) return 'text-emerald-400'
  if (pct < 0.66) return 'text-amber-400'
  return 'text-red-400'
}

// ── Sub-components ────────────────────────────────────────────────────────────

function QualityBar({ score }: { score: number }) {
  const color =
    score >= 85 ? 'from-emerald-500 to-emerald-400'
    : score >= 70 ? 'from-blue-500 to-blue-400'
    : 'from-amber-500 to-amber-400'
  return (
    <div className="flex items-center gap-2">
      <div className="w-20 h-1.5 rounded-full bg-[#1c2a3a] overflow-hidden">
        <div
          className={`h-full rounded-full bg-gradient-to-r ${color} transition-all`}
          style={{ width: `${score}%` }}
        />
      </div>
      <span className="text-xs text-slate-500">{Math.round(score)}</span>
    </div>
  )
}

function Spinner({ size = 'sm' }: { size?: 'sm' | 'md' }) {
  const cls = size === 'sm' ? 'w-4 h-4' : 'w-6 h-6'
  return (
    <div
      className={`${cls} border-2 border-blue-500 border-t-transparent rounded-full animate-spin`}
    />
  )
}

function Badge({ children, variant = 'default' }: {
  children: React.ReactNode
  variant?: 'default' | 'blue' | 'amber' | 'emerald'
}) {
  const styles = {
    default: 'bg-[#1c2a3a] text-slate-400',
    blue: 'bg-blue-500/10 text-blue-400 border border-blue-500/20',
    amber: 'bg-amber-500/10 text-amber-400 border border-amber-500/20',
    emerald: 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20',
  }
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${styles[variant]}`}>
      {children}
    </span>
  )
}

function InputLabel({ children }: { children: React.ReactNode }) {
  return (
    <label className="text-xs font-medium text-slate-400 uppercase tracking-wider mb-1.5 block">
      {children}
    </label>
  )
}

const inputCls =
  'w-full bg-[#111827] border border-[#1f2937] rounded-lg px-3.5 py-2.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500/20 transition'

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function Home() {
  // Form state
  const [procedure, setProcedure] = useState('')
  const [cptCandidates, setCptCandidates] = useState<CPTCandidate[]>([])
  const [selectedCpt, setSelectedCpt] = useState<CPTCandidate | null>(null)
  const [cptLoading, setCptLoading] = useState(false)

  const [zip, setZip] = useState('60601')
  const [radius, setRadius] = useState(25)
  const [planId, setPlanId] = useState('AETNA-PPO-IL-2026')
  const [deductible, setDeductible] = useState('700')
  const [coinsurance, setCoinsurance] = useState(20)
  const [oopMax, setOopMax] = useState('2300')
  const [costWeight, setCostWeight] = useState(60)

  // Results state
  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState<SearchResults | null>(null)
  const [error, setError] = useState('')
  const [expandedNpi, setExpandedNpi] = useState<string | null>(null)

  // ── CPT lookup (debounced) ───────────────────────────────────────────────
  useEffect(() => {
    if (procedure.length < 3) {
      setCptCandidates([])
      if (procedure.length === 0) setSelectedCpt(null)
      return
    }
    setCptLoading(true)
    const timer = setTimeout(async () => {
      try {
        const res = await fetch('/api/cpt-lookup', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query: procedure }),
        })
        if (res.ok) {
          const data = await res.json()
          const candidates: CPTCandidate[] = data.cpt_candidates ?? []
          setCptCandidates(candidates)
          if (candidates.length > 0) setSelectedCpt(candidates[0])
        }
      } catch {
        // fail silently — user can still type a CPT manually
      } finally {
        setCptLoading(false)
      }
    }, 600)
    return () => clearTimeout(timer)
  }, [procedure])

  // ── Search ────────────────────────────────────────────────────────────────
  const handleSearch = async (e: FormEvent) => {
    e.preventDefault()
    if (!selectedCpt) {
      setError('Enter a procedure above to get a CPT code, then search.')
      return
    }
    setLoading(true)
    setError('')
    setResults(null)
    setExpandedNpi(null)
    try {
      const res = await fetch('/api/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          cpt_code: selectedCpt.cpt_code,
          plan_id: planId.trim() || undefined,
          zip: zip.trim(),
          radius_miles: radius,
          deductible_remaining: parseFloat(deductible) || 0,
          coinsurance_pct: coinsurance / 100,
          oop_max_remaining: parseFloat(oopMax) || 0,
          weights: { cost: costWeight / 100, quality: 1 - costWeight / 100 },
          limit: 15,
          include_timeline: true,
        }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail ?? 'Search failed')
      setResults(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Search failed. Check that the API is running.')
    } finally {
      setLoading(false)
    }
  }

  const toggleExpand = (npi: string) =>
    setExpandedNpi((prev) => (prev === npi ? null : npi))

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-[#060a14] text-slate-200 font-sans">

      {/* ── Header ── */}
      <header className="sticky top-0 z-20 border-b border-[#1c2a3a] bg-[#060a14]/90 backdrop-blur-sm px-6 py-4">
        <div className="max-w-5xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            {/* Logo mark */}
            <div className="w-8 h-8 rounded-lg bg-blue-500 flex items-center justify-center flex-shrink-0">
              <svg viewBox="0 0 24 24" className="w-4 h-4" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/>
                <polyline points="9,22 9,12 15,12 15,22"/>
              </svg>
            </div>
            <div>
              <div className="font-semibold text-white leading-tight tracking-tight">AnaCare</div>
              <div className="text-xs text-slate-500 leading-tight">Intelligence Platform</div>
            </div>
          </div>
          <Badge variant="emerald">Demo · Aetna PPO Chicago</Badge>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-10">

        {/* ── Hero ── */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-white tracking-tight mb-2">
            Find the best provider for any procedure
          </h1>
          <p className="text-slate-400">
            Real negotiated rates · Out-of-pocket estimates · CMS quality scores · Ranked for your plan
          </p>
        </div>

        {/* ── Search Form ── */}
        <form
          onSubmit={handleSearch}
          className="bg-[#0d1421] border border-[#1c2a3a] rounded-xl p-6 mb-8 space-y-5"
        >
          {/* Procedure */}
          <div>
            <InputLabel>Procedure</InputLabel>
            <div className="relative">
              <input
                type="text"
                value={procedure}
                onChange={(e) => { setProcedure(e.target.value); setSelectedCpt(null) }}
                placeholder="e.g. knee replacement, colonoscopy, MRI knee…"
                className={inputCls}
                autoComplete="off"
              />
              {cptLoading && (
                <div className="absolute right-3 top-1/2 -translate-y-1/2">
                  <Spinner />
                </div>
              )}
            </div>

            {/* CPT tags */}
            {cptCandidates.length > 0 && (
              <div className="mt-2 flex items-center gap-2 flex-wrap">
                <span className="text-xs text-slate-600">Mapped to:</span>
                {cptCandidates.slice(0, 4).map((c) => (
                  <button
                    key={c.cpt_code}
                    type="button"
                    onClick={() => setSelectedCpt(c)}
                    className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
                      selectedCpt?.cpt_code === c.cpt_code
                        ? 'border-blue-500 bg-blue-500/10 text-blue-400'
                        : 'border-[#1f2937] text-slate-500 hover:border-slate-500 hover:text-slate-400'
                    }`}
                  >
                    {c.cpt_code} · {c.label}
                    <span className="ml-1 opacity-50">{Math.round(c.confidence * 100)}%</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Zip / Radius / Plan */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div>
              <InputLabel>ZIP Code</InputLabel>
              <input
                type="text"
                value={zip}
                onChange={(e) => setZip(e.target.value)}
                maxLength={5}
                placeholder="60601"
                className={inputCls}
                required
              />
            </div>
            <div>
              <InputLabel>Radius</InputLabel>
              <select
                value={radius}
                onChange={(e) => setRadius(Number(e.target.value))}
                className={inputCls}
              >
                <option value={10}>10 miles</option>
                <option value={25}>25 miles</option>
                <option value={50}>50 miles</option>
              </select>
            </div>
            <div>
              <InputLabel>
                Plan ID <span className="text-slate-600 normal-case font-normal">(optional)</span>
              </InputLabel>
              <input
                type="text"
                value={planId}
                onChange={(e) => setPlanId(e.target.value)}
                placeholder="AETNA-PPO-IL-2026"
                className={inputCls}
              />
            </div>
          </div>

          {/* Insurance details */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div>
              <InputLabel>Deductible Remaining</InputLabel>
              <div className="relative">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 text-sm select-none">$</span>
                <input
                  type="number"
                  value={deductible}
                  onChange={(e) => setDeductible(e.target.value)}
                  min={0}
                  placeholder="700"
                  className={`${inputCls} pl-7`}
                  required
                />
              </div>
            </div>
            <div>
              <InputLabel>Coinsurance</InputLabel>
              <div className="relative">
                <input
                  type="number"
                  value={coinsurance}
                  onChange={(e) => setCoinsurance(Number(e.target.value))}
                  min={0}
                  max={100}
                  placeholder="20"
                  className={`${inputCls} pr-8`}
                  required
                />
                <span className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 text-sm select-none">%</span>
              </div>
            </div>
            <div>
              <InputLabel>OOP Max Remaining</InputLabel>
              <div className="relative">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 text-sm select-none">$</span>
                <input
                  type="number"
                  value={oopMax}
                  onChange={(e) => setOopMax(e.target.value)}
                  min={0}
                  placeholder="2300"
                  className={`${inputCls} pl-7`}
                  required
                />
              </div>
            </div>
          </div>

          {/* Ranking weights + submit */}
          <div className="flex flex-col sm:flex-row items-start sm:items-end gap-4">
            <div className="flex-1 w-full">
              <InputLabel>Ranking Priority</InputLabel>
              <div className="flex items-center gap-3">
                <span className="text-xs text-slate-500 w-16 text-right tabular-nums">Cost {costWeight}%</span>
                <input
                  type="range"
                  min={0}
                  max={100}
                  step={10}
                  value={costWeight}
                  onChange={(e) => setCostWeight(Number(e.target.value))}
                  className="flex-1"
                />
                <span className="text-xs text-slate-500 w-16 tabular-nums">Quality {100 - costWeight}%</span>
              </div>
            </div>
            <button
              type="submit"
              disabled={loading || !selectedCpt}
              className="w-full sm:w-auto px-6 py-2.5 rounded-lg bg-blue-500 hover:bg-blue-400 active:bg-blue-600 disabled:bg-[#1c2a3a] disabled:text-slate-500 disabled:cursor-not-allowed text-white font-medium text-sm transition-colors flex items-center gap-2 justify-center min-w-[150px]"
            >
              {loading ? (
                <>
                  <Spinner />
                  Searching…
                </>
              ) : (
                'Find Providers →'
              )}
            </button>
          </div>
        </form>

        {/* ── Error ── */}
        {error && (
          <div className="mb-6 p-4 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm animate-fadeIn">
            {error}
          </div>
        )}

        {/* ── Results ── */}
        {results && (
          <div className="space-y-3 animate-fadeIn">

            {/* Results summary bar */}
            <div className="flex items-center justify-between mb-5">
              <div>
                <h2 className="font-semibold text-white text-lg">
                  {results.result_count} provider{results.result_count !== 1 ? 's' : ''} found
                </h2>
                <p className="text-xs text-slate-500 mt-0.5">
                  Ranked by{' '}
                  {results.ranking_basis === 'cost_only' ? 'cost only' : 'cost + quality'}
                  {' · '}
                  {results.meta.total_providers_evaluated} evaluated
                  {' · '}
                  {results.meta.latency_ms}ms
                </p>
              </div>
              {results.ranking_basis === 'cost_only' && (
                <Badge variant="amber">Quality data sparse — cost-only ranking</Badge>
              )}
            </div>

            {/* Warnings */}
            {results.warnings.map((w, i) => (
              <div
                key={i}
                className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-400 text-xs"
              >
                {w}
              </div>
            ))}

            {/* Column headers */}
            <div className="hidden sm:grid grid-cols-12 gap-4 px-4 py-2 text-xs text-slate-600 uppercase tracking-wider">
              <div className="col-span-1">#</div>
              <div className="col-span-5">Provider</div>
              <div className="col-span-3 text-right">Est. OOP</div>
              <div className="col-span-3">Quality</div>
            </div>

            {/* Provider cards */}
            {results.results.map((provider, idx) => (
              <div
                key={provider.npi}
                className="result-card bg-[#0d1421] border border-[#1c2a3a] rounded-xl overflow-hidden"
                style={{ animationDelay: `${idx * 40}ms` }}
              >
                {/* Main row */}
                <div
                  className="grid grid-cols-12 gap-4 items-center px-4 py-4 cursor-pointer hover:bg-[#111e30] transition-colors"
                  onClick={() => toggleExpand(provider.npi)}
                  role="button"
                  aria-expanded={expandedNpi === provider.npi}
                >
                  {/* Rank */}
                  <div className="col-span-1">
                    <div
                      className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0 ${
                        idx === 0
                          ? 'bg-blue-500 text-white'
                          : 'bg-[#1c2a3a] text-slate-400'
                      }`}
                    >
                      {provider.rank}
                    </div>
                  </div>

                  {/* Provider info */}
                  <div className="col-span-7 sm:col-span-5 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-medium text-white text-sm leading-snug">
                        {provider.provider_name}
                      </span>
                      {idx === 0 && <Badge variant="blue">Best Value</Badge>}
                    </div>
                    <div className="text-xs text-slate-400 mt-0.5">
                      {provider.specialty}
                      {provider.distance_miles > 0 && (
                        <span className="text-slate-600">
                          {' · '}{provider.distance_miles.toFixed(1)} mi
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-slate-600 mt-0.5 truncate">
                      {[provider.address, provider.city, provider.state]
                        .filter(Boolean)
                        .join(', ')}
                    </div>
                  </div>

                  {/* OOP */}
                  <div className="col-span-4 sm:col-span-3 text-right">
                    <div
                      className={`text-lg font-bold tabular-nums ${oopColorClass(
                        provider.estimated_oop,
                        results.results
                      )}`}
                    >
                      {formatOOP(provider.estimated_oop)}
                      {provider.estimated_oop === 0 && (
                        <span className="block text-xs font-normal text-slate-500">ACA covered</span>
                      )}
                    </div>
                    {provider.estimated_oop > 0 && (
                      <div className="text-xs text-slate-600">est. out-of-pocket</div>
                    )}
                  </div>

                  {/* Quality — hidden on very small screens */}
                  <div className="hidden sm:flex sm:col-span-3 items-center gap-2">
                    {provider.quality_score !== null ? (
                      <QualityBar score={provider.quality_score} />
                    ) : (
                      <span className="text-xs text-slate-600">—</span>
                    )}
                    <svg
                      className={`w-3.5 h-3.5 text-slate-600 ml-auto transition-transform flex-shrink-0 ${
                        expandedNpi === provider.npi ? 'rotate-180' : ''
                      }`}
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                      strokeWidth={2}
                    >
                      <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                    </svg>
                  </div>
                </div>

                {/* Expanded details */}
                {expandedNpi === provider.npi && (
                  <div className="px-4 pb-4 border-t border-[#1c2a3a] pt-4 animate-fadeIn">
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                      <div>
                        <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">
                          Negotiated Rate
                        </div>
                        <div className="font-semibold text-slate-200 text-sm">
                          {formatRate(provider.negotiated_rate)}
                        </div>
                      </div>
                      {provider.quality_signals.cms_outcome_rating !== undefined && (
                        <div>
                          <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">
                            CMS Rating
                          </div>
                          <div className="font-semibold text-slate-200 text-sm">
                            {provider.quality_signals.cms_outcome_rating.toFixed(1)}{' '}
                            <span className="text-slate-500 font-normal">/ 5.0</span>
                          </div>
                        </div>
                      )}
                      {provider.quality_signals.procedure_volume !== undefined && (
                        <div>
                          <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">
                            Annual Volume
                          </div>
                          <div className="font-semibold text-slate-200 text-sm">
                            {provider.quality_signals.procedure_volume.toLocaleString()}
                            <span className="text-slate-500 font-normal"> procedures</span>
                          </div>
                        </div>
                      )}
                      {provider.quality_signals.patient_satisfaction !== undefined && (
                        <div>
                          <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">
                            Patient Satisfaction
                          </div>
                          <div className="font-semibold text-slate-200 text-sm">
                            {provider.quality_signals.patient_satisfaction}
                            <span className="text-slate-500 font-normal">%</span>
                          </div>
                        </div>
                      )}
                    </div>

                    {/* Notes */}
                    {provider.notes && provider.notes.length > 0 && (
                      <div className="mt-3 flex gap-2 flex-wrap">
                        {provider.notes.map((note, i) => (
                          <span
                            key={i}
                            className="text-xs px-2 py-0.5 rounded-full bg-[#1c2a3a] text-slate-400"
                          >
                            {note}
                          </span>
                        ))}
                      </div>
                    )}

                    {/* Cost Timeline */}
                    {provider.timeline && provider.timeline.timeline_points.length > 0 && (
                      <div className="mt-4">
                        <div className="text-xs text-slate-500 uppercase tracking-wider mb-2">
                          Cost Timeline
                        </div>
                        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                          {provider.timeline.timeline_points.map((tp) => (
                            <div
                              key={tp.months}
                              className="bg-[#111827] border border-[#1f2937] rounded-lg px-3 py-2"
                            >
                              <div className="text-xs text-slate-500 mb-1">{tp.label}</div>
                              <div className="font-semibold text-slate-200 text-sm tabular-nums">
                                {formatOOP(tp.net_out_of_pocket)}
                              </div>
                              <div className="text-xs text-slate-600 mt-0.5">net OOP</div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* NPI */}
                    <div className="mt-3 text-xs text-slate-600">
                      NPI <span className="font-mono">{provider.npi}</span>
                    </div>
                  </div>
                )}
              </div>
            ))}

            {/* Disclaimer */}
            <p className="text-xs text-slate-600 mt-4 p-3 rounded-lg border border-[#1c2a3a] leading-relaxed">
              {results.disclaimer}
            </p>
          </div>
        )}

        {/* ── Empty state ── */}
        {!results && !loading && !error && (
          <div className="text-center py-16 text-slate-600">
            <div className="w-12 h-12 rounded-xl bg-[#0d1421] border border-[#1c2a3a] flex items-center justify-center mx-auto mb-4">
              <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 15.803 7.5 7.5 0 0015.803 15.803z"/>
              </svg>
            </div>
            <p className="text-sm">Enter a procedure and your insurance details to find ranked providers.</p>
          </div>
        )}
      </main>
    </div>
  )
}
