"use strict";
const $ = id => document.getElementById(id);
const controls = ["search", "location", "country", "workplace", "contract", "company", "match", "period", "sort"];
const workplaceLabels = { remote: "Remote · 远程", onsite: "On-site · 现场", hybrid: "Hybrid · 混合", unknown: "办公方式未注明" };
const contractLabels = { intern: "Intern · 实习", fulltime: "Full-time · 全职", parttime: "Part-time · 兼职", contract: "Contract · 合同", unknown: "性质未注明" };
let data = { jobs: [], sources: [] }, page = 1;
const pageSize = 25;
const escaped = value => String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
function safeUrl(value) { try { const u = new URL(value); return ["https:", "http:"].includes(u.protocol) ? escaped(u.href) : "#"; } catch { return "#"; } }
const age = value => (Date.now() - new Date(value).getTime()) / 86400000;
function date(value, time = false) {
  if (!value || Number.isNaN(new Date(value).getTime())) return "未提供";
  return new Intl.DateTimeFormat("zh-CN", { timeZone: data.timezone || "Australia/Sydney", year: "numeric", month: "2-digit", day: "2-digit", ...(time ? { hour: "2-digit", minute: "2-digit", hour12: false } : {}) }).format(new Date(value));
}
function render() {
  for (const [id, value] of [["all-jobs", ""], ["intern-jobs", "intern"]]) {
    const active = $("contract").value === value;
    $(id).classList.toggle("active", active);
    $(id).setAttribute("aria-pressed", String(active));
  }
  const query = $("search").value.toLowerCase().trim().split(/\s+/).filter(Boolean);
  const location = $("location").value.toLowerCase().trim();
  const period = Number($("period").value);
  const rows = data.jobs.filter(job => {
    const haystack = `${job.title} ${job.company} ${job.department} ${job.excerpt}`.toLowerCase();
    return query.every(word => haystack.includes(word)) && job.location.toLowerCase().includes(location)
      && (!$("company").value || job.company === $("company").value)
      && (!$("match").value || job.match === $("match").value)
      && (!period || age(job.first_seen) <= period)
      && (!$("country").value || ($("country").value === "unknown" ? !job.countries.length : job.countries.includes($("country").value)))
      && (!$("workplace").value || job.workplace === $("workplace").value)
      && (!$("contract").value || job.contract === $("contract").value);
  });
  rows.sort((a, b) => {
    if ($("sort").value === "company") return a.company.localeCompare(b.company) || a.title.localeCompare(b.title);
    if ($("sort").value === "title" && a.match !== b.match) return a.match === "title" ? -1 : 1;
    return b.first_seen.localeCompare(a.first_seen) || a.company.localeCompare(b.company);
  });
  const pages = Math.max(1, Math.ceil(rows.length / pageSize));
  page = Math.min(page, pages);
  $("result-count").textContent = `${rows.length.toLocaleString()} 个结果`;
  $("jobs").innerHTML = rows.slice((page - 1) * pageSize, page * pageSize).map(job => `<article class="job">
    <div class="job-top"><span class="company-name">${escaped(job.company)}</span>${age(job.first_seen) <= 1 ? '<span class="badge new">新发现</span>' : ""}${job.match === "title" ? '<span class="badge match">标题含 C++</span>' : '<span class="badge">JD 提及 C++</span>'}${job.contract === "intern" ? '<span class="badge intern">实习 / Co-op</span>' : ""}</div>
    <h3><a href="${safeUrl(job.url)}" target="_blank" rel="noopener noreferrer">${escaped(job.title)}</a></h3>
    <div class="job-meta"><span class="place">${escaped(job.location)}</span><span>${escaped(workplaceLabels[job.workplace] || workplaceLabels.unknown)}</span><span>${escaped(contractLabels[job.contract] || contractLabels.unknown)}</span>${job.salary ? `<span>${escaped(job.salary)}</span>` : ""}</div>
    <p class="excerpt">${escaped(job.excerpt)}</p>
    <div class="job-bottom"><span class="discovery">首次发现 ${date(job.first_seen)} · 最近确认 ${date(job.last_seen)}${job.posted_at ? `<br>来源发布日期 ${date(job.posted_at)}` : ""}</span><a class="jd-link" href="${safeUrl(job.url)}" target="_blank" rel="noopener noreferrer" aria-label="查看 ${escaped(job.company)} ${escaped(job.title)} 的原始 JD">查看 JD ↗</a></div></article>`).join("") || '<div class="empty">没有符合条件的岗位。<br>试试其他关键词，或重置筛选条件。</div>';
  $("page-info").textContent = `${page} / ${pages}`;
  $("prev").disabled = page === 1;
  $("next").disabled = page === pages;
}
function reset() { for (const id of controls) { if ($(id).tagName === "SELECT") $(id).selectedIndex = 0; else $(id).value = ""; } page = 1; render(); }
controls.forEach(id => $(id).addEventListener(["search", "location"].includes(id) ? "input" : "change", () => { page = 1; render(); }));
$("reset").addEventListener("click", reset);
$("filter-toggle").addEventListener("click", () => {
  const expanded = $("filter-panel").classList.toggle("is-open");
  $("filter-toggle").setAttribute("aria-expanded", String(expanded));
  $("filter-toggle").textContent = expanded ? "收起筛选 −" : "筛选岗位 · 国家 / 办公方式 / 工作性质 ＋";
});
for (const [id, value] of [["all-jobs", ""], ["intern-jobs", "intern"]]) $(id).addEventListener("click", () => { $("contract").value = value; page = 1; render(); });
for (const [id, delta] of [["prev", -1], ["next", 1]]) $(id).addEventListener("click", () => { page += delta; render(); $("results").scrollIntoView({ block: "start" }); });
async function init() {
  try {
    const response = await fetch("jobs.json", { cache: "no-cache" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    data = await response.json();
    if (!Array.isArray(data.jobs) || !Array.isArray(data.sources)) throw new Error("Invalid job data");
    const companies = [...new Set(data.jobs.map(j => j.company))].sort();
    $("company").innerHTML = '<option value="">全部公司</option>' + companies.map(c => `<option value="${escaped(c)}">${escaped(c)}</option>`).join("");
    const countries = [...new Set(data.jobs.flatMap(j => j.countries))].sort((a, b) => (data.country_labels[a] || a).localeCompare(data.country_labels[b] || b, "zh-CN"));
    $("country").innerHTML = '<option value="">全部国家 / 地区</option>' + countries.map(c => `<option value="${escaped(c)}">${escaped(data.country_labels[c] || c)}</option>`).join("") + '<option value="unknown">未注明 / 无法识别</option>';
    $("total").textContent = data.jobs.length.toLocaleString();
    $("new-total").textContent = data.jobs.filter(j => age(j.first_seen) <= 1).length.toLocaleString();
    $("companies-total").textContent = companies.length;
    $("intern-total").textContent = data.jobs.filter(j => j.contract === "intern").length;
    $("sources-total").textContent = `${data.sources.filter(s => s.ok).length}/${data.sources.length}`;
    $("last-update").textContent = `最近抓取 ${date(data.last_attempt, true)}`;
    $("source-summary").textContent = `${data.sources.length} 个公司招聘源`;
    $("source-list").innerHTML = data.sources.map(s => `<div class="source-row"><b>${escaped(s.company)}</b><span class="${s.ok ? "" : "failed"}">${s.ok ? `${s.eligible ?? s.matched} 个显示 / ${s.excluded ?? 0} 个身份限制` : "暂时失败 · 保留已检查数据"}</span></div>`).join("");
    if (data.screening) $("screening-note").textContent = `身份限制过滤已开启：排除 ${data.screening.excluded} 个有公民、国籍、永居、U.S. Person 或强制安全许可要求的岗位${data.screening.unreviewed ? `，另有 ${data.screening.unreviewed} 个待检查岗位暂不展示` : ""}。其余岗位未检出上述限制，工作许可与签证条件仍需核对 JD。`;
    const failed = data.sources.filter(s => !s.ok).length;
    const warnings = [];
    if (failed) warnings.push(`${failed} 个招聘源本次未能更新，相关岗位保留上次抓取结果。`);
    if (!data.last_success || age(data.last_success) > 2) warnings.push("数据已超过 48 小时未成功更新，请查看页面底部的运行记录。");
    if (warnings.length) { $("notice").hidden = false; $("notice").textContent = warnings.join(" "); }
    render();
  } catch (error) {
    $("jobs").innerHTML = '<div class="empty">岗位数据暂时无法加载。<br>请稍后刷新，或查看 GitHub 运行记录。</div>';
    $("result-count").textContent = "加载失败";
    $("last-update").textContent = "未能读取更新信息";
    console.error("Unable to load jobs", error);
  }
}
init();
