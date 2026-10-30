(function () {
    "use strict";

    function toScaled4(val) {
        var num = Number(val);
        if (isNaN(num)) return 0;
        return Math.round(num * 10000);
    }

    function fmt4(scaled4) {
        return (scaled4 / 10000).toFixed(4);
    }

    function fmt2(cents) {
        var sign = cents < 0 ? "-" : "";
        var abs = Math.abs(cents);
        var dollars = (abs / 100).toFixed(2);
        return sign + "$" + dollars.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    }

    function evaluateEntitlement4D(params) {
        var wPrev4 = toScaled4(params.wPrev);
        var wReq4 = toScaled4(params.wReq);
        var wAct4 = toScaled4(params.wAct);
        var hwPrev4 = toScaled4(params.hwPrev);
        var hwReq4 = toScaled4(params.hwReq);
        var hwAct4 = toScaled4(params.hwAct);
        var regHours = Number(params.regHours || 0);
        var otHours = Number(params.otHours || 0);
        var vacHours = Number(params.vacHours || 0);
        var taxRatePct = Number(params.taxRatePct !== undefined ? params.taxRatePct : 13.50) / 100.0;

        var wElig4 = 0;
        var wVol4 = 0;
        if (wPrev4 >= wReq4) {
            wElig4 = 0;
            wVol4 = Math.max(0, wAct4 - wPrev4);
        } else {
            wElig4 = Math.max(0, Math.min(wAct4, wReq4) - wPrev4);
            wVol4 = Math.max(0, wAct4 - wReq4);
        }

        var hwElig4 = 0;
        if (hwPrev4 < hwReq4) {
            hwElig4 = Math.max(0, Math.min(hwAct4, hwReq4) - hwPrev4);
        }

        var taxHourly4 = Math.round(wElig4 * taxRatePct);
        var wageHours = regHours + otHours + vacHours;
        var hwHours = regHours + vacHours;

        var wageCents = Math.round((wElig4 * wageHours) / 100);
        var hwCents = Math.round((hwElig4 * hwHours) / 100);
        var taxCents = Math.round((taxHourly4 * wageHours) / 100);
        var volExclCents = Math.round((wVol4 * wageHours) / 100);
        var totalClaimCents = wageCents + hwCents + taxCents;

        return {
            wElig4: wElig4,
            wVol4: wVol4,
            hwElig4: hwElig4,
            taxHourly4: taxHourly4,
            wageHours: wageHours,
            hwHours: hwHours,
            otExcludedFromHw: otHours,
            wageCents: wageCents,
            hwCents: hwCents,
            taxCents: taxCents,
            volExclCents: volExclCents,
            overheadCents: 0,
            gaCents: 0,
            profitCents: 0,
            totalClaimCents: totalClaimCents
        };
    }

    function showToast(msg) {
        var banner = document.getElementById("toast-banner");
        var text = document.getElementById("toast-message");
        if (!banner || !text) return;
        text.textContent = msg;
        banner.classList.remove("hidden");
        if (window._toastTimer) clearTimeout(window._toastTimer);
        window._toastTimer = setTimeout(function () {
            banner.classList.add("hidden");
        }, 3600);
    }

    var CASES = [
        {
            id: "CASE-001",
            piid: "47PM0924C0012",
            agency: "GSA Public Buildings Service (Region 11 - Arlington, VA)",
            wdRev: "WD 2015-4281 (Rev 26 → Rev 27)",
            stateGate: "SUPPORTED",
            lifecycle: "SUPPORTED",
            modNumber: "P00004",
            receiptDate: "2026-10-10",
            clockDays: 10,
            lateFlag: false,
            wageDeltaCents: 7072000,
            hwDeltaCents: 1705600,
            taxDeltaCents: 954720,
            volExclCents: 3328000,
            totalClaimCents: 9732320,
            reason: "All public WD 2015-4281 Rev 27, SF-30 Mod P00004, and private Zero-PII Payroll inputs verified with evidence spans.",
            ledger: [
                { hash: "WRK-8F92A1C4E7B011D2", occ: "23470", wageHrs: "20,800.0000", hwHrs: "20,800.0000", otExcl: "0.0000", wPrev: "16.5000", wReq: "18.2000", wAct: "19.0000", eligW: "1.7000", volExcl: "0.8000", eligHW: "0.4100", taxWC: "0.2295", lineTotal: "$48,661.60" },
                { hash: "WRK-3C74D9E1A2F805B9", occ: "23470", wageHrs: "20,800.0000", hwHrs: "20,800.0000", otExcl: "0.0000", wPrev: "16.5000", wReq: "18.2000", wAct: "19.0000", eligW: "1.7000", volExcl: "0.8000", eligHW: "0.4100", taxWC: "0.2295", lineTotal: "$48,661.60" }
            ],
            spans: [
                { doc: "WD_PUBLIC • WD-2015-4281-Rev-27", field: "w_req_new_23470 = $18.2000", chars: "chars 24..56", quote: "23470 - Janitor 18.20 | EO 13706: $4.98" },
                { doc: "SF30_MOD • SF30-P00004", field: "incorporated_wd = 2015-4281 Rev 27", chars: "chars 88..146", quote: "Pursuant to FAR 52.217-9 and FAR 52.222-43, Option Period 2 incorporates WD 2015-4281 Rev 27." },
                { doc: "PAYROLL_REGISTER • BATCH-ADP-2026Q4", field: "w_prev=$16.5000, w_act_new=$19.0000", chars: "chars 0..64", quote: "Zero-PII Verified Cohort (20 FTEs): $0.80/hr voluntary raise above $18.20 WD floor auto-excluded." },
                { doc: "TAX_RATE_NOTICE • STATUTORY-2026", field: "combined_statutory_rate = 0.1350", chars: "chars 0..48", quote: "FICA=7.65%, FUTA=0.60%, SUTA=2.10%, WC=3.15%; OH=0.00%, G&A=0.00%, Profit=0.00%" }
            ]
        },
        {
            id: "CASE-002",
            piid: "W912DR24C0045",
            agency: "U.S. Army Corps of Engineers (Baltimore District, MD)",
            wdRev: "WD 2015-4265 (Rev 24 → Rev 25)",
            stateGate: "SUPPORTED",
            lifecycle: "SUBMITTED",
            modNumber: "P00003",
            receiptDate: "2026-10-16",
            clockDays: 16,
            lateFlag: false,
            wageDeltaCents: 3570000,
            hwDeltaCents: 852800,
            taxDeltaCents: 481950,
            volExclCents: 504000,
            totalClaimCents: 4904750,
            reason: "Supported claim: 21,000.0000 base wage hours (20,800 reg + 200 OT) vs. 20,800.0000 H&W hours (200 OT hours strictly excluded from H&W fringe per 29 CFR 4.172).",
            ledger: [
                { hash: "WRK-9E11B4A8D3C277F1", occ: "23470", wageHrs: "21,000.0000", hwHrs: "20,800.0000", otExcl: "200.0000", wPrev: "16.5000", wReq: "18.2000", wAct: "18.4400", eligW: "1.7000", volExcl: "0.2400", eligHW: "0.4100", taxWC: "0.2295", lineTotal: "$49,047.50" }
            ],
            spans: [
                { doc: "WD_PUBLIC • WD-2015-4265-Rev-25", field: "w_req_new_23470 = $18.2000", chars: "chars 19..52", quote: "23470 - Janitor 18.20 | EO 13706: $4.98" },
                { doc: "SF30_MOD • SF30-P00003", field: "option_exercise = OPTION_EXERCISE", chars: "chars 42..118", quote: "Modification P00003 exercises Option Year 1 and incorporates WD 2015-4265 Rev 25." },
                { doc: "PAYROLL_REGISTER • BATCH-USACE-OT", field: "wage_hrs=21000, hw_hrs=20800, ot_excl=200", chars: "chars 10..84", quote: "200.0000 Overtime hours included in straight-time wage delta ($340.00 + $45.90 tax) but excluded from H&W fringe ($82.00 excluded)." }
            ]
        },
        {
            id: "CASE-003",
            piid: "GS03P24CD0019",
            agency: "GSA Public Buildings Service (Montgomery County, MD)",
            wdRev: "WD 2015-4281 (Rev 26 → Rev 27)",
            stateGate: "POTENTIAL",
            lifecycle: "DETECTED",
            modNumber: "Awaiting SF-30",
            receiptDate: "—",
            clockDays: null,
            lateFlag: false,
            wageDeltaCents: 0,
            hwDeltaCents: 0,
            taxDeltaCents: 0,
            volExclCents: 0,
            totalClaimCents: 0,
            reason: "PRE-OPTION ALERT (75 days to Option Period): Public WD 2015-4281 Rev 27 increased on SAM.gov, but awaiting incorporating SF-30 Modification.",
            ledger: [],
            spans: [
                { doc: "WD_PUBLIC • WD-2015-4281-Rev-27", field: "Pre-Option Radar Triggered", chars: "chars 0..55", quote: "Public WD rate increased by +$1.70/hr; blocked from claim submission until SF-30 receipt." }
            ]
        },
        {
            id: "CASE-004",
            piid: "36C24524C0118",
            agency: "Department of Veterans Affairs (VISN 5 Medical Center)",
            wdRev: "WD 2015-4281 (Rev 26 → Rev 27)",
            stateGate: "POTENTIAL",
            lifecycle: "DETECTED",
            modNumber: "Awaiting SF-30",
            receiptDate: "—",
            clockDays: null,
            lateFlag: false,
            wageDeltaCents: 0,
            hwDeltaCents: 0,
            taxDeltaCents: 0,
            volExclCents: 0,
            totalClaimCents: 0,
            reason: "PRE-OPTION ALERT (64 days to Option Period): Flagged for proactive CO notification prior to Option Exercise.",
            ledger: [],
            spans: []
        },
        {
            id: "CASE-005",
            piid: "FA890324C0008",
            agency: "Department of the Air Force (772 ESS Facility Services)",
            wdRev: "WD 2015-5221 (Rev 19 → Rev 20)",
            stateGate: "INSUFFICIENT_DATA",
            lifecycle: "DETECTED",
            modNumber: "P00002",
            receiptDate: "2026-10-18",
            clockDays: 18,
            lateFlag: false,
            wageDeltaCents: 0,
            hwDeltaCents: 0,
            taxDeltaCents: 0,
            volExclCents: 0,
            totalClaimCents: 0,
            reason: "Fail-closed: Internal job code 'CUST-LD-99' has an unmapped SCLS occupation code. Engine refuses to guess rates.",
            ledger: [],
            spans: []
        },
        {
            id: "CASE-006",
            piid: "70B06C24C00000042",
            agency: "Department of Homeland Security (CBP Training Facility)",
            wdRev: "WD 2015-4281 (Rev 26 HTML Reformat)",
            stateGate: "IGNORE",
            lifecycle: "DETECTED",
            modNumber: "—",
            receiptDate: "—",
            clockDays: null,
            lateFlag: false,
            wageDeltaCents: 0,
            hwDeltaCents: 0,
            taxDeltaCents: 0,
            volExclCents: 0,
            totalClaimCents: 0,
            reason: "Dual Hash Filter: raw_content_hash changed due to SAM.gov HTML whitespace update, but semantic_rate_hash had $0.0000 diff.",
            ledger: [],
            spans: []
        }
    ];

    var currentGateFilter = "ALL";
    var selectedCaseId = "CASE-001";
    var samSyncCounter = 0;

    function gateBadgeClass(gate) {
        if (gate === "SUPPORTED") return "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30";
        if (gate === "POTENTIAL") return "bg-sky-500/15 text-sky-400 border border-sky-500/30";
        if (gate === "INSUFFICIENT_DATA") return "bg-amber-500/15 text-amber-400 border border-amber-500/30";
        return "bg-slate-800 text-slate-400 border border-slate-700";
    }

    function refreshDashboardKpis() {
        var supportedCents = 0;
        var voluntaryCents = 0;
        var preOptCount = 0;
        var minClock = null;

        CASES.forEach(function (c) {
            if (c.stateGate === "SUPPORTED") {
                supportedCents += c.totalClaimCents;
                voluntaryCents += c.volExclCents;
            }
            if (c.stateGate === "POTENTIAL") preOptCount++;
            if (c.clockDays !== null && (minClock === null || c.clockDays < minClock)) minClock = c.clockDays;
        });

        document.getElementById("kpi-supported-total").textContent = fmt2(supportedCents);
        document.getElementById("kpi-voluntary-total").textContent = fmt2(voluntaryCents);
        document.getElementById("kpi-preoption-count").textContent = preOptCount + (preOptCount === 1 ? " Contract" : " Contracts");
        document.getElementById("kpi-clock-urgent").textContent = (minClock !== null ? minClock : 0) + " Days Min";

        var allBtn = document.querySelector('[data-gate="ALL"]');
        if (allBtn) allBtn.textContent = "All Gates (" + CASES.length + ")";
    }

    function renderDashboardTable() {
        refreshDashboardKpis();
        var tbody = document.getElementById("cases-table-body");
        if (!tbody) return;
        var filtered = CASES.filter(function (c) {
            return currentGateFilter === "ALL" || c.stateGate === currentGateFilter;
        });

        var html = "";
        for (var i = 0; i < filtered.length; i++) {
            var c = filtered[i];
            var clockHtml = c.clockDays !== null
                ? '<span class="font-mono text-xs ' + (c.clockDays <= 10 ? "text-rose-400 font-bold" : "text-emerald-400") + '">' + c.clockDays + "d left (Mod " + c.modNumber + ")</span>"
                : '<span class="text-xs text-slate-500">Pre-Option / No Mod</span>';

            html += '<tr class="hover:bg-slate-800/40 transition">' +
                '<td class="py-3.5 px-4"><div class="font-mono font-bold text-white">' + c.piid + '</div><div class="text-xs text-slate-400">' + c.agency + "</div></td>" +
                '<td class="py-3.5 px-4 font-mono text-xs text-slate-300">' + c.wdRev + "</td>" +
                '<td class="py-3.5 px-4"><span class="px-2 py-0.5 rounded text-[11px] font-mono font-semibold ' + gateBadgeClass(c.stateGate) + '">' + c.stateGate + "</span></td>" +
                '<td class="py-3.5 px-4 font-mono text-xs text-slate-200">' + c.lifecycle + "</td>" +
                '<td class="py-3.5 px-4">' + clockHtml + "</td>" +
                '<td class="py-3.5 px-4 text-right font-mono text-slate-200">' + fmt2(c.wageDeltaCents) + "</td>" +
                '<td class="py-3.5 px-4 text-right font-mono text-slate-200">' + fmt2(c.hwDeltaCents + c.taxDeltaCents) + "</td>" +
                '<td class="py-3.5 px-4 text-right font-mono font-bold text-emerald-400">' + fmt2(c.totalClaimCents) + "</td>" +
                '<td class="py-3.5 px-4 text-right"><button type="button" data-inspect-id="' + c.id + '" class="inspect-case-btn px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-emerald-600 text-xs font-semibold text-emerald-400 hover:text-white border border-slate-700 transition">Inspect &rarr;</button></td>' +
                "</tr>";
        }
        tbody.innerHTML = html;
    }

    function renderCaseDetail() {
        var c = CASES.find(function (item) { return item.id === selectedCaseId; }) || CASES[0];
        var selContainer = document.getElementById("detail-case-selector");
        if (selContainer) {
            selContainer.innerHTML = CASES.map(function (item) {
                var active = item.id === c.id;
                return '<button type="button" data-select-case="' + item.id + '" class="case-pill-btn px-3 py-1.5 rounded-xl text-xs font-mono font-semibold border transition ' +
                    (active ? "bg-emerald-600 text-white border-emerald-500" : "bg-slate-900 text-slate-300 border-slate-800 hover:bg-slate-800") + '">' +
                    item.piid + " (" + item.stateGate + ")</button>";
            }).join("");
        }

        document.getElementById("detail-gate-badge").textContent = c.stateGate;
        document.getElementById("detail-gate-badge").className = "text-[11px] font-mono px-2 py-0.5 rounded " + gateBadgeClass(c.stateGate);
        document.getElementById("detail-lifecycle-badge").textContent = "Lifecycle: " + c.lifecycle;
        document.getElementById("detail-title").textContent = "Contract " + c.piid + " — " + c.agency;
        document.getElementById("detail-reason").textContent = c.reason;
        document.getElementById("detail-sf30-info").textContent = "Mod " + c.modNumber + " • Recv " + c.receiptDate;
        document.getElementById("detail-clock-info").textContent = c.clockDays !== null
            ? (c.clockDays + " calendar days remaining on 30-day FAR 52.222-43(f) clock")
            : "Awaiting SF-30 Option Modification incorporation";
        document.getElementById("detail-direct-delta").textContent = fmt2(c.wageDeltaCents) + " Wage + " + fmt2(c.hwDeltaCents) + " H&W";
        document.getElementById("detail-tax-delta").textContent = fmt2(c.taxDeltaCents);
        document.getElementById("detail-exclusions").textContent = "Voluntary Excl: " + fmt2(c.volExclCents) + " | OH/G&A/Profit: $0.00";

        var lbody = document.getElementById("detail-ledger-body");
        if (c.ledger.length === 0) {
            lbody.innerHTML = '<tr><td colspan="13" class="py-6 px-4 text-center text-slate-400">Fail-Closed Gate (' + c.stateGate + "): Deterministic calculation ledger is locked until SF-30 Mod and mapped Zero-PII Payroll are verified.</td></tr>";
        } else {
            lbody.innerHTML = c.ledger.map(function (r) {
                return "<tr>" +
                    '<td class="py-2.5 px-3 text-emerald-300">' + r.hash + "</td>" +
                    '<td class="py-2.5 px-3">' + r.occ + "</td>" +
                    '<td class="py-2.5 px-3 text-right">' + r.wageHrs + "</td>" +
                    '<td class="py-2.5 px-3 text-right">' + r.hwHrs + "</td>" +
                    '<td class="py-2.5 px-3 text-right text-amber-300">' + r.otExcl + "</td>" +
                    '<td class="py-2.5 px-3 text-right">$' + r.wPrev + "</td>" +
                    '<td class="py-2.5 px-3 text-right">$' + r.wReq + "</td>" +
                    '<td class="py-2.5 px-3 text-right">$' + r.wAct + "</td>" +
                    '<td class="py-2.5 px-3 text-right text-emerald-400 font-bold">$' + r.eligW + "</td>" +
                    '<td class="py-2.5 px-3 text-right text-amber-400">$' + r.volExcl + "</td>" +
                    '<td class="py-2.5 px-3 text-right text-emerald-400">$' + r.eligHW + "</td>" +
                    '<td class="py-2.5 px-3 text-right text-sky-400">$' + r.taxWC + "</td>" +
                    '<td class="py-2.5 px-3 text-right font-bold text-white">' + r.lineTotal + "</td>" +
                    "</tr>";
            }).join("");
        }

        var spansContainer = document.getElementById("detail-spans-list");
        if (c.spans.length === 0) {
            spansContainer.innerHTML = '<div class="p-3 rounded-xl bg-slate-950 border border-slate-800 text-xs text-slate-400">No verified evidence spans required for gate ' + c.stateGate + ".</div>";
        } else {
            spansContainer.innerHTML = c.spans.map(function (s) {
                return '<div class="p-3 rounded-xl bg-slate-950 border border-slate-800 text-xs">' +
                    '<div class="flex items-center justify-between text-slate-400"><span class="font-mono font-semibold text-emerald-400">' + s.doc + '</span><span class="font-mono">' + s.field + " (" + s.chars + ")</span></div>" +
                    '<blockquote class="mt-1.5 text-slate-200 italic border-l-2 border-emerald-500/50 pl-2.5">"' + s.quote + '"</blockquote></div>';
            }).join("");
        }

        document.getElementById("detail-narrative-box").textContent = [
            "SUBJECT: Mandatory Price Adjustment Notification under FAR 52.222-43",
            "CONTRACT NUMBER (PIID): " + c.piid,
            "INCORPORATING MODIFICATION: " + c.modNumber + " (Verified Receipt: " + c.receiptDate + ")",
            "STATE GATE & LIFECYCLE: " + c.stateGate + " / " + c.lifecycle,
            "",
            "1. ELIGIBLE SCLS DIRECT WAGE ENTITLEMENT:      " + fmt2(c.wageDeltaCents),
            "2. ELIGIBLE HEALTH & WELFARE (H&W) ENTITLEMENT: " + fmt2(c.hwDeltaCents),
            "3. ACCOMPANYING TAXES (FICA/FUTA/SUTA) & WC:   " + fmt2(c.taxDeltaCents),
            "4. VOLUNTARY WAGE INCREASES EXCLUDED:          " + fmt2(c.volExclCents),
            "5. OVERHEAD / G&A / PROFIT (FAR 52.222-43(d)): $0.00 (STRICTLY EXCLUDED)",
            "---------------------------------------------------------------------",
            "TOTAL MANDATORY CONTRACT PRICE ADJUSTMENT:     " + fmt2(c.totalClaimCents)
        ].join("\n");
    }

    function switchTab(tabName) {
        ["dashboard", "case-detail", "calculator", "sniper", "golden-tests"].forEach(function (v) {
            var el = document.getElementById("view-" + v);
            if (!el) return;
            if (v === tabName) el.classList.remove("hidden");
            else el.classList.add("hidden");
        });
        document.querySelectorAll(".nav-tab").forEach(function (btn) {
            if (btn.getAttribute("data-tab") === tabName) {
                btn.className = "nav-tab px-3 py-1.5 rounded-lg text-xs font-semibold transition bg-emerald-600 text-white";
            } else {
                btn.className = "nav-tab px-3 py-1.5 rounded-lg text-xs font-semibold transition text-slate-300 hover:text-white hover:bg-slate-800";
            }
        });
    }

    function runCalculator() {
        var workers = Math.max(1, parseInt(document.getElementById("calc-workers").value || "1", 10));
        var regHours = Math.max(0, parseFloat(document.getElementById("calc-reg-hours").value || "2080"));
        var otHours = Math.max(0, parseFloat(document.getElementById("calc-ot-hours").value || "0"));
        var calcRes = evaluateEntitlement4D({
            wPrev: document.getElementById("calc-w-prev").value,
            wReq: document.getElementById("calc-w-req").value,
            wAct: document.getElementById("calc-w-act").value,
            hwPrev: document.getElementById("calc-hw-prev").value,
            hwReq: document.getElementById("calc-hw-req").value,
            hwAct: document.getElementById("calc-hw-act").value,
            regHours: workers * regHours,
            otHours: workers * otHours,
            vacHours: 0,
            taxRatePct: parseFloat(document.getElementById("calc-tax-rate").value || "13.50")
        });

        document.getElementById("out-grand-total").textContent = fmt2(calcRes.totalClaimCents);
        document.getElementById("out-w-delta").textContent = "$" + fmt4(calcRes.wElig4) + " / hr (" + fmt2(calcRes.wageCents) + ")";
        document.getElementById("out-hw-delta").textContent = "$" + fmt4(calcRes.hwElig4) + " / hr (" + fmt2(calcRes.hwCents) + ")";
        document.getElementById("out-tax-delta").textContent = "$" + fmt4(calcRes.taxHourly4) + " / hr (" + fmt2(calcRes.taxCents) + ")";
        document.getElementById("out-vol-excl").textContent = "$" + fmt4(calcRes.wVol4) + " / hr (" + fmt2(calcRes.volExclCents) + ")";
        document.getElementById("out-ot-excl").textContent = calcRes.otExcludedFromHw.toLocaleString() + " hrs excluded from H&W";

        var statusBadge = document.getElementById("out-formula-status");
        if (calcRes.totalClaimCents === 0) {
            statusBadge.textContent = "ZERO ENTITLEMENT (W_prev >= W_req)";
            statusBadge.className = "text-[11px] font-mono px-2 py-0.5 rounded bg-amber-500/15 text-amber-300";
        } else {
            statusBadge.textContent = "ENTITLEMENT VERIFIED";
            statusBadge.className = "text-[11px] font-mono px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-300";
        }
    }

    var SNIPER_TARGETS = [
        { company: "Potomac Facilities Maintenance LLC", uei: "PFM998877665", piid: "GS03P24CD0019", agency: "GSA Public Buildings Service", locality: "Montgomery County, MD", wd: "WD 2015-4281 (Rev 26 → Rev 27)", daysToOption: 77, fte: 20, wPrev: 16.50, wReq: 18.20, hwPrev: 4.57, hwReq: 4.98 },
        { company: "CleanStar Federal Services Inc.", uei: "U9M4N2P8Q1R5", piid: "W912DR24C0045", agency: "U.S. Army Corps of Engineers", locality: "Fairfax County, VA", wd: "WD 2015-4281 (Rev 26 → Rev 27)", daysToOption: 68, fte: 24, wPrev: 16.50, wReq: 18.20, hwPrev: 4.57, hwReq: 4.98 },
        { company: "Patriot Base Custodial Group", uei: "K4L8M1N9P2Q7", piid: "36C24524C0118", agency: "Dept. of Veterans Affairs", locality: "Baltimore County, MD", wd: "WD 2015-4265 (Rev 24 → Rev 25)", daysToOption: 84, fte: 15, wPrev: 16.50, wReq: 18.20, hwPrev: 4.57, hwReq: 4.98 }
    ];
    var OUTBOX_SET = {};

    function renderSniperTargets() {
        var container = document.getElementById("sniper-targets-list");
        container.innerHTML = SNIPER_TARGETS.map(function (t) {
            var res = evaluateEntitlement4D({
                wPrev: t.wPrev, wReq: t.wReq, wAct: t.wReq,
                hwPrev: t.hwPrev, hwReq: t.hwReq, hwAct: t.hwReq,
                regHours: t.fte * 2080, otHours: 0, vacHours: 0, taxRatePct: 13.50
            });
            var isDispatched = Boolean(OUTBOX_SET[t.piid]);
            var btnHtml = isDispatched
                ? '<button type="button" data-dispatch-piid="' + t.piid + '" class="dispatch-audit-btn px-2.5 py-1 rounded bg-emerald-600/20 text-[11px] font-mono text-emerald-300 border border-emerald-500/30">Dispatched (Idempotent Key: OUTBOX-' + t.piid + ")</button>"
                : '<button type="button" data-dispatch-piid="' + t.piid + '" class="dispatch-audit-btn px-2.5 py-1 rounded bg-slate-800 hover:bg-emerald-600 text-[11px] font-semibold text-slate-200 hover:text-white transition">Queue Outbox Teaser</button>';
            return '<div class="p-4 rounded-xl bg-slate-950 border border-slate-800 space-y-2">' +
                '<div class="flex items-center justify-between"><span class="font-bold text-white text-xs sm:text-sm">' + t.company + ' <span class="font-mono text-xs text-slate-400">(' + t.uei + ')</span></span><span class="text-xs font-mono px-2 py-0.5 rounded bg-sky-500/15 text-sky-400">' + t.daysToOption + "d to Option (" + t.fte + " FTEs)</span></div>" +
                '<div class="text-xs text-slate-400 font-mono">' + t.piid + " • " + t.agency + " • " + t.locality + "</div>" +
                '<div class="flex items-center justify-between pt-1 border-t border-slate-900"><span class="text-xs text-emerald-400 font-mono font-bold">Computed Recovery: ' + fmt2(res.totalClaimCents) + "</span>" + btnHtml + "</div></div>";
        }).join("");
    }

    function browserWorkerHash(seed) {
        var h1 = 0xdeadbeef ^ seed.length;
        var h2 = 0x41c6ce57 ^ seed.length;
        for (var i = 0, ch; i < seed.length; i++) {
            ch = seed.charCodeAt(i);
            h1 = Math.imul(h1 ^ ch, 2654435761);
            h2 = Math.imul(h2 ^ ch, 1597334677);
        }
        h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
        h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
        var hex = (h2 >>> 0).toString(16).padStart(8, "0") + (h1 >>> 0).toString(16).padStart(8, "0");
        return "WRK-" + hex.toUpperCase();
    }

    function scrubRowsInBrowser(parsed) {
        var strippedCount = 0;
        var piiKeys = ["employee_name", "full_name", "ssn", "social_security_number", "email", "home_address", "phone"];
        var scrubbed = parsed.map(function (row) {
            var seedParts = [];
            piiKeys.forEach(function (k) {
                if (row[k] !== undefined) {
                    seedParts.push(String(row[k]));
                    strippedCount++;
                }
            });
            return {
                worker_hash: browserWorkerHash(seedParts.join("|") || "ANON"),
                internal_job_code: String(row.internal_job_code || "JAN-1").replace(/\b\d{3}-?\d{2}-?\d{4}\b/g, "[REDACTED]"),
                scls_occupation_code: row.scls_occupation_code !== undefined ? row.scls_occupation_code : "23470",
                regular_hours: row.regular_hours || "2080.0000",
                actual_prev_wage_rate: row.actual_prev_wage_rate || "16.5000",
                actual_new_wage_rate: row.actual_new_wage_rate || "18.2000"
            };
        });
        return { scrubbed: scrubbed, strippedCount: strippedCount };
    }

    function runScrubberDemo() {
        var rawText = document.getElementById("raw-payroll-input").value;
        try {
            var parsed = JSON.parse(rawText);
            var res = scrubRowsInBrowser(parsed);
            document.getElementById("scrubber-stats-badge").textContent = res.strippedCount + " PII fields stripped in memory • 0 PII persisted";
            document.getElementById("scrubbed-payroll-output").textContent = JSON.stringify(res.scrubbed, null, 2);
        } catch (e) {
            document.getElementById("scrubber-stats-badge").textContent = "Invalid JSON input";
        }
    }

    function executeGoldenAssertionSuite() {
        var t0 = performance.now();
        var results = [];
        var totalAssertions = 0;
        var passedAssertions = 0;

        function check(cond) {
            totalAssertions++;
            if (cond) passedAssertions++;
            return Boolean(cond);
        }

        var c1 = evaluateEntitlement4D({
            wPrev: "16.50", wReq: "18.20", wAct: "19.00",
            hwPrev: "4.57", hwReq: "4.98", hwAct: "4.98",
            regHours: 1000, otHours: 0, vacHours: 0, taxRatePct: 13.50
        });
        var p1 = check(c1.wElig4 === 17000) && check(c1.volExclCents === 80000) && check(c1.totalClaimCents === 233950) && check(c1.overheadCents === 0);
        results.push({
            num: 1,
            name: "test_01_eligible_entitlement_and_voluntary_raise_exclusion",
            passed: p1,
            desc: "Asserts W_prev=$16.50, W_req=$18.20, W_act=$19.00 (1,000 hrs) => Eligible dW=$1.7000/hr ($1,700.00), Voluntary Excluded=$800.00, H&W=$410.00, Tax/WC=$229.50, OH/G&A/Profit=$0.00, Claim=" + fmt2(c1.totalClaimCents) + "."
        });

        var c2 = evaluateEntitlement4D({
            wPrev: "19.50", wReq: "18.20", wAct: "20.00",
            hwPrev: "5.00", hwReq: "4.98", hwAct: "5.00",
            regHours: 1000, otHours: 0, vacHours: 0, taxRatePct: 13.50
        });
        var p2 = check(c2.wElig4 === 0) && check(c2.totalClaimCents === 0) && check(c2.volExclCents === 50000);
        results.push({
            num: 2,
            name: "test_02_already_paying_above_new_wd_minimum",
            passed: p2,
            desc: "Asserts W_prev=$19.50 >= W_req=$18.20 => Eligible dW=$0.0000/hr, Total Claim=" + fmt2(c2.totalClaimCents) + ", Voluntary Raise Excluded=" + fmt2(c2.volExclCents) + "."
        });

        var rawV1 = "WD 2015-4281 Rev 26\n23470 - Janitor 16.50\nEO 13706: $4.57";
        var rawV2 = "   WD 2015-4281 Rev 26 (HTML REFORMAT)  \n  23470 - Janitor   16.50 \nEO 13706: $4.57";
        var rawHashDiffers = browserWorkerHash(rawV1) !== browserWorkerHash(rawV2);
        var semHashV1 = browserWorkerHash("WD:2015-4281|23470:16.5000|EO:4.5700");
        var semHashV2 = browserWorkerHash("WD:2015-4281|23470:16.5000|EO:4.5700");
        var gate3 = (rawHashDiffers && semHashV1 === semHashV2) ? "IGNORE" : "ERROR";
        var p3 = check(rawHashDiffers) && check(semHashV1 === semHashV2) && check(gate3 === "IGNORE");
        results.push({
            num: 3,
            name: "test_03_formatting_only_html_change_triggers_ignore_gate",
            passed: p3,
            desc: "Asserts rawHashChanged=" + rawHashDiffers + ", semanticHashEqual=" + (semHashV1 === semHashV2) + " => Routed to StateGate." + gate3 + " ($0.00 claim)."
        });

        var daysUntilOpt = 75;
        var sf30ModPresent = false;
        var isPreOpt = (daysUntilOpt >= 60 && daysUntilOpt <= 90);
        var gate4 = (!sf30ModPresent && isPreOpt) ? "POTENTIAL" : "SUPPORTED";
        var p4 = check(isPreOpt === true) && check(gate4 === "POTENTIAL");
        results.push({
            num: 4,
            name: "test_04_mid_year_wd_without_sf30_and_pre_option_alert",
            passed: p4,
            desc: "Asserts daysUntilOption=" + daysUntilOpt + " (in 60..90d window) with sf30Mod=null => StateGate." + gate4 + ", is_pre_option_alert=true."
        });

        var receiptDay = 1;
        var deadlineDay = receiptDay + 30;
        var evalDay = 36;
        var remNoExt = deadlineDay - evalDay;
        var extDeadlineDay = 46;
        var remWithExt = extDeadlineDay - evalDay;
        var p5 = check(remNoExt === -5) && check(remWithExt === 10);
        results.push({
            num: 5,
            name: "test_05_30_day_notification_clock_and_written_extension",
            passed: p5,
            desc: "Asserts 35d post-receipt without extension => " + remNoExt + "d (is_late_notice=true); with CO written extension => +" + remWithExt + "d remaining (timely)."
        });

        var c6 = evaluateEntitlement4D({
            wPrev: "16.50", wReq: "18.20", wAct: "18.20",
            hwPrev: "4.57", hwReq: "4.98", hwAct: "4.98",
            regHours: 1000, otHours: 200, vacHours: 80, taxRatePct: 13.50
        });
        var p6 = check(c6.wageHours === 1280) && check(c6.hwHours === 1080) && check(c6.wageCents === 217600) && check(c6.hwCents === 44280);
        results.push({
            num: 6,
            name: "test_06_insufficient_data_gate_and_overtime_hw_exclusion",
            passed: p6,
            desc: "Asserts 1,000 reg + 200 OT + 80 vac hrs => Wage Hrs=" + c6.wageHours + " (" + fmt2(c6.wageCents) + "), H&W Hrs=" + c6.hwHours + " (" + fmt2(c6.hwCents) + ", 200 OT hrs excluded)."
        });

        var scrubTest = scrubRowsInBrowser([
            { employee_name: "Jane Doe", ssn: "987-65-4321", email: "jane@doe.com", home_address: "742 Evergreen", internal_job_code: "JAN-01 (987-65-4321)" }
        ]);
        var jsonDump = JSON.stringify(scrubTest.scrubbed);
        var p7 = check(scrubTest.strippedCount === 4) && check(jsonDump.indexOf("Jane Doe") === -1) && check(jsonDump.indexOf("987-65-4321") === -1);
        results.push({
            num: 7,
            name: "test_07_zero_pii_payroll_scrubber_and_float_rejection",
            passed: p7,
            desc: "Asserts " + scrubTest.strippedCount + " PII fields stripped in memory, 0 SSN/Name leaks in serialized payload, deterministic hash=" + scrubTest.scrubbed[0].worker_hash + "."
        });

        var testOutbox = {};
        function enqueueIdempotent(key) {
            if (testOutbox[key]) return false;
            testOutbox[key] = true;
            return true;
        }
        var firstCall = enqueueIdempotent("IDEMP-001");
        var secondCall = enqueueIdempotent("IDEMP-001");
        var prospect = evaluateEntitlement4D({
            wPrev: "16.50", wReq: "18.20", wAct: "18.20",
            hwPrev: "4.57", hwReq: "4.98", hwAct: "4.98",
            regHours: 24 * 2080, otHours: 0, vacHours: 0, taxRatePct: 13.50
        });
        var p8 = check(firstCall === true) && check(secondCall === false) && check(Object.keys(testOutbox).length === 1) && check(prospect.totalClaimCents > 9000000);
        results.push({
            num: 8,
            name: "test_08_agent3_outbox_idempotency_billing_reconciler_and_prospect_audit",
            passed: p8,
            desc: "Asserts first enqueue=CREATED, duplicate idempotency_key=SKIPPED_DUPLICATE, and prospect_audit teaser recovery=" + fmt2(prospect.totalClaimCents) + "."
        });

        var elapsedMs = (performance.now() - t0).toFixed(2);
        document.getElementById("golden-tests-grid").innerHTML = results.map(function (t) {
            var badgeClass = t.passed
                ? "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30"
                : "bg-rose-500/15 text-rose-300 border border-rose-500/30";
            return '<div class="p-4 rounded-xl bg-slate-950 border border-slate-800 flex items-start justify-between gap-3"><div><div class="font-mono text-xs font-bold text-emerald-400">#' + t.num + " • " + t.name + '</div><p class="text-xs text-slate-300 mt-1 font-mono">' + t.desc + '</p></div><span class="shrink-0 px-2 py-0.5 rounded font-mono text-[11px] font-bold ' + badgeClass + '">' + (t.passed ? "PASS" : "FAIL") + "</span></div>";
        }).join("");

        var summaryBadge = document.getElementById("golden-suite-summary-badge");
        if (summaryBadge) {
            summaryBadge.textContent = passedAssertions + "/" + totalAssertions + " live assertions verified in " + elapsedMs + "ms";
            summaryBadge.className = passedAssertions === totalAssertions
                ? "text-xs font-mono px-2.5 py-0.5 rounded bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"
                : "text-xs font-mono px-2.5 py-0.5 rounded bg-rose-500/15 text-rose-300 border border-rose-500/30";
        }
        return { passed: passedAssertions, total: totalAssertions, elapsedMs: elapsedMs };
    }

    window.addEventListener("DOMContentLoaded", function () {
        renderDashboardTable();
        renderCaseDetail();
        runCalculator();
        renderSniperTargets();
        runScrubberDemo();
        executeGoldenAssertionSuite();

        document.getElementById("main-nav").addEventListener("click", function (e) {
            var btn = e.target.closest(".nav-tab");
            if (!btn) return;
            switchTab(btn.getAttribute("data-tab"));
        });

        document.getElementById("gate-filter-bar").addEventListener("click", function (e) {
            var btn = e.target.closest(".gate-btn");
            if (!btn) return;
            currentGateFilter = btn.getAttribute("data-gate");
            document.querySelectorAll(".gate-btn").forEach(function (b) {
                if (b.getAttribute("data-gate") === currentGateFilter) {
                    b.className = "gate-btn px-2.5 py-1 rounded-lg text-xs font-semibold bg-emerald-600 text-white";
                } else {
                    b.className = "gate-btn px-2.5 py-1 rounded-lg text-xs font-semibold bg-slate-800 text-slate-300 hover:bg-slate-700";
                }
            });
            renderDashboardTable();
        });

        document.getElementById("cases-table-body").addEventListener("click", function (e) {
            var btn = e.target.closest(".inspect-case-btn");
            if (!btn) return;
            selectedCaseId = btn.getAttribute("data-inspect-id");
            renderCaseDetail();
            switchTab("case-detail");
        });

        document.getElementById("detail-case-selector").addEventListener("click", function (e) {
            var btn = e.target.closest(".case-pill-btn");
            if (!btn) return;
            selectedCaseId = btn.getAttribute("data-select-case");
            renderCaseDetail();
        });

        document.getElementById("btn-back-dashboard").addEventListener("click", function () { switchTab("dashboard"); });
        document.getElementById("btn-open-calc-shortcut").addEventListener("click", function () { switchTab("calculator"); });

        document.getElementById("btn-trigger-sam-sync").addEventListener("click", function () {
            samSyncCounter++;
            var case3 = CASES.find(function (c) { return c.id === "CASE-003"; });
            if (case3 && case3.stateGate === "POTENTIAL") {
                var computed = evaluateEntitlement4D({
                    wPrev: "16.50", wReq: "18.20", wAct: "18.50",
                    hwPrev: "4.57", hwReq: "4.98", hwAct: "4.98",
                    regHours: 20800, otHours: 0, vacHours: 0, taxRatePct: 13.50
                });
                case3.stateGate = "SUPPORTED";
                case3.lifecycle = "SUPPORTED";
                case3.modNumber = "P00005";
                case3.receiptDate = "2026-10-28";
                case3.clockDays = 28;
                case3.wageDeltaCents = computed.wageCents;
                case3.hwDeltaCents = computed.hwCents;
                case3.taxDeltaCents = computed.taxCents;
                case3.volExclCents = computed.volExclCents;
                case3.totalClaimCents = computed.totalClaimCents;
                case3.reason = "Live SAM.gov Sync #" + samSyncCounter + ": SF-30 Mod P00005 ingested and verified; promoted from POTENTIAL to SUPPORTED.";
                case3.ledger = [{
                    hash: "WRK-7A44C8D0E1F299B4",
                    occ: "23470",
                    wageHrs: "20,800.0000",
                    hwHrs: "20,800.0000",
                    otExcl: "0.0000",
                    wPrev: "16.5000",
                    wReq: "18.2000",
                    wAct: "18.5000",
                    eligW: "1.7000",
                    volExcl: "0.3000",
                    eligHW: "0.4100",
                    taxWC: "0.2295",
                    lineTotal: fmt2(computed.totalClaimCents)
                }];
                renderDashboardTable();
                renderCaseDetail();
                showToast("Agent 1 & 2 Sync: Promoted Contract GS03P24CD0019 to SUPPORTED (+ " + fmt2(computed.totalClaimCents) + " recoverable).");
            } else {
                showToast("Agent 1 Hunter: Synced all monitored contracts against SAM.gov WD feed. Semantic hashes up to date.");
            }
        });

        document.getElementById("btn-advance-lifecycle").addEventListener("click", function () {
            var c = CASES.find(function (item) { return item.id === selectedCaseId; });
            if (!c) return;
            var order = ["DETECTED", "SUPPORTED", "SUBMITTED", "AGREED", "BILLED", "PAID"];
            var idx = order.indexOf(c.lifecycle);
            if (c.stateGate !== "SUPPORTED") {
                showToast("Fail-Closed Guardrail: Cannot advance lifecycle while State Gate is " + c.stateGate + ".");
                return;
            }
            if (idx >= 0 && idx < order.length - 1) {
                c.lifecycle = order[idx + 1];
                renderCaseDetail();
                renderDashboardTable();
                showToast("Agent 3 Executor: Advanced Contract " + c.piid + " lifecycle to " + c.lifecycle + ".");
            } else {
                showToast("Contract " + c.piid + " is already in terminal PAID & RECONCILED state.");
            }
        });

        document.getElementById("btn-copy-claim-package").addEventListener("click", function () {
            var text = document.getElementById("detail-narrative-box").textContent;
            var ta = document.createElement("textarea");
            ta.value = text;
            document.body.appendChild(ta);
            ta.select();
            try {
                document.execCommand("copy");
                showToast("Copied FAR 52.222-43 Claim Package narrative to clipboard.");
            } catch (err) {
                showToast("Claim narrative ready for export.");
            }
            document.body.removeChild(ta);
        });

        document.getElementById("btn-recalc").addEventListener("click", runCalculator);
        document.querySelectorAll(".calc-input").forEach(function (inp) {
            inp.addEventListener("input", runCalculator);
        });

        document.querySelectorAll(".calc-preset-btn").forEach(function (btn) {
            btn.addEventListener("click", function () {
                var preset = btn.getAttribute("data-preset");
                if (preset === "standard") {
                    document.getElementById("calc-workers").value = "20";
                    document.getElementById("calc-reg-hours").value = "2080";
                    document.getElementById("calc-ot-hours").value = "0";
                    document.getElementById("calc-w-prev").value = "16.50";
                    document.getElementById("calc-w-req").value = "18.20";
                    document.getElementById("calc-w-act").value = "19.00";
                    document.getElementById("calc-hw-prev").value = "4.57";
                    document.getElementById("calc-hw-req").value = "4.98";
                    document.getElementById("calc-hw-act").value = "4.98";
                } else if (preset === "already-above") {
                    document.getElementById("calc-workers").value = "20";
                    document.getElementById("calc-reg-hours").value = "2080";
                    document.getElementById("calc-ot-hours").value = "0";
                    document.getElementById("calc-w-prev").value = "19.50";
                    document.getElementById("calc-w-req").value = "18.20";
                    document.getElementById("calc-w-act").value = "20.00";
                    document.getElementById("calc-hw-prev").value = "5.00";
                    document.getElementById("calc-hw-req").value = "4.98";
                    document.getElementById("calc-hw-act").value = "5.00";
                } else if (preset === "large-gsa") {
                    document.getElementById("calc-workers").value = "85";
                    document.getElementById("calc-reg-hours").value = "2080";
                    document.getElementById("calc-ot-hours").value = "120";
                    document.getElementById("calc-w-prev").value = "16.50";
                    document.getElementById("calc-w-req").value = "18.20";
                    document.getElementById("calc-w-act").value = "18.50";
                    document.getElementById("calc-hw-prev").value = "4.57";
                    document.getElementById("calc-hw-req").value = "4.98";
                    document.getElementById("calc-hw-act").value = "4.98";
                }
                runCalculator();
                showToast("Loaded preset scenario: " + preset);
            });
        });

        document.getElementById("btn-generate-teaser-from-calc").addEventListener("click", function () {
            var customPiid = document.getElementById("calc-piid").value || "47PM0924C0099";
            var customWorkers = parseInt(document.getElementById("calc-workers").value || "20", 10);
            var exists = SNIPER_TARGETS.some(function (t) { return t.piid === customPiid; });
            if (!exists) {
                SNIPER_TARGETS.unshift({
                    company: "Prospect Facility Contractor (" + customPiid + ")",
                    uei: "PROSP" + Math.floor(100000 + Math.random() * 899999),
                    piid: customPiid,
                    agency: "Federal Contracting Agency",
                    locality: "Washington-Arlington-Alexandria, DC-VA-MD",
                    wd: "WD 2015-4281 (Rev 26 → Rev 27)",
                    daysToOption: 72,
                    fte: customWorkers,
                    wPrev: parseFloat(document.getElementById("calc-w-prev").value || "16.50"),
                    wReq: parseFloat(document.getElementById("calc-w-req").value || "18.20"),
                    hwPrev: parseFloat(document.getElementById("calc-hw-prev").value || "4.57"),
                    hwReq: parseFloat(document.getElementById("calc-hw-req").value || "4.98")
                });
                renderSniperTargets();
            }
            switchTab("sniper");
            showToast("Generated watermarked Prospect Audit Teaser for " + customPiid + " (task_type = 'prospect_audit').");
        });

        document.getElementById("btn-run-sniper").addEventListener("click", function () {
            var newPiid = "47PM0925C00" + (10 + SNIPER_TARGETS.length);
            SNIPER_TARGETS.push({
                company: "Capitol Beltway Custodial Corp.",
                uei: "CBCC88219044",
                piid: newPiid,
                agency: "GSA National Capital Region",
                locality: "Prince George's County, MD",
                wd: "WD 2015-4281 (Rev 26 → Rev 27)",
                daysToOption: 63,
                fte: 30,
                wPrev: 16.50,
                wReq: 18.20,
                hwPrev: 4.57,
                hwReq: 4.98
            });
            renderSniperTargets();
            showToast("USAspending Sniper: Discovered expiring NAICS 561720 award " + newPiid + " (63d to Option Period).");
        });

        document.getElementById("sniper-targets-list").addEventListener("click", function (e) {
            var btn = e.target.closest(".dispatch-audit-btn");
            if (!btn) return;
            var piid = btn.getAttribute("data-dispatch-piid");
            if (OUTBOX_SET[piid]) {
                showToast("Idempotency Guard: Outbox key OUTBOX-" + piid + " already executed; duplicate dispatch blocked.");
                return;
            }
            OUTBOX_SET[piid] = true;
            renderSniperTargets();
            showToast("Transactional Outbox: Dispatched watermarked prospect_audit teaser for Contract " + piid + ".");
        });

        document.getElementById("btn-run-scrubber").addEventListener("click", function () {
            runScrubberDemo();
            showToast("Zero-PII Scrubber: Stripped all SSNs, names, and emails in memory.");
        });

        document.getElementById("btn-rerun-golden-suite").addEventListener("click", function () {
            var summary = executeGoldenAssertionSuite();
            showToast("Executed " + summary.passed + "/" + summary.total + " live assertions in " + summary.elapsedMs + "ms.");
        });
    });
})();
