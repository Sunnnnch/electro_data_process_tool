(function () {
  "use strict";

  const API = window.ElectrochemApi || { fetch: (...args) => window.fetch(...args) };

  function jsonRequest(payload) {
    return {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
    };
  }

  function conversationListUrl(options) {
    const opts = options || {};
    const query = new URLSearchParams();
    query.set("page", String(opts.page || 1));
    query.set("page_size", String(opts.pageSize || 30));
    if (opts.keyword) {
      query.set("keyword", String(opts.keyword));
    }
    return `/api/v1/agent/conversations?${query.toString()}`;
  }

  function listConversations(options) {
    return API.fetch(conversationListUrl(options));
  }

  function getConversation(conversationId) {
    return API.fetch(`/api/v1/agent/conversations/${encodeURIComponent(conversationId)}`);
  }

  function deleteConversation(conversationId) {
    return API.fetch(
      `/api/v1/agent/conversations/${encodeURIComponent(conversationId)}/delete`,
      jsonRequest({})
    );
  }

  function renameConversation(conversationId, title) {
    return API.fetch(
      `/api/v1/agent/conversations/${encodeURIComponent(conversationId)}/rename`,
      jsonRequest({ title })
    );
  }

  function sendMessageForm(formData) {
    return API.fetch("/api/v1/agent/messages", { method: "POST", body: formData });
  }

  function submitMessageJobForm(formData) {
    return API.fetch("/api/v1/agent/jobs", { method: "POST", body: formData });
  }

  function sendMessageJson(payload) {
    return API.fetch("/api/v1/agent/messages", jsonRequest(payload));
  }

  function submitMessageJob(payload) {
    return API.fetch("/api/v1/agent/jobs", jsonRequest(payload));
  }

  function getMessageJob(jobId) {
    return API.fetch(`/api/v1/agent/jobs/${encodeURIComponent(jobId)}`);
  }

  function cancelMessageJob(jobId) {
    return API.fetch(`/api/v1/agent/jobs/${encodeURIComponent(jobId)}/cancel`, jsonRequest({}));
  }

  window.ElectrochemAssistantApi = {
    cancelMessageJob,
    conversationListUrl,
    deleteConversation,
    getConversation,
    getMessageJob,
    listConversations,
    renameConversation,
    sendMessageForm,
    sendMessageJson,
    submitMessageJob,
    submitMessageJobForm,
  };
})();
