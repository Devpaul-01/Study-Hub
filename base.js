document.addEventListener("DOMContentLoaded", () => {
  updatePage();

  async function updatePage() {
    const ntfSpan = document.getElementById("notif-count");
    const msgSpan = document.getElementById("msg-count");

    try {
      const response = await api.get("/profile/counts");

      if (response.status === "success") {
        const ntfCounts = response.data.notifications;
        const msgCounts = response.data.messages;
        ntfSpan.textContent = ntfCounts;
        msgSpan.textContent = msgCounts;
      }
    } catch (error) {
      // do nothing
    }
  }
});