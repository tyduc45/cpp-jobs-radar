"use strict";
// Apply the server's deadline again in the browser, even if scheduled builds stop.
const RadarFreshness = {
  currentJobs(data, now = Date.now()) {
    return data.jobs.filter(job => job.active && Date.parse(job.visible_until) > now);
  },
  hiddenCount(data, now = Date.now()) {
    return (data.freshness?.hidden_unverified || 0) + data.jobs.length - this.currentJobs(data, now).length;
  }
};
if (typeof module !== "undefined") module.exports = RadarFreshness;
