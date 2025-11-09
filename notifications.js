document.addEventListener("DOMContentLoaded", () => {
  const tabs = document.querySelectorAll(".tab");
  const tabContents = document.querySelectorAll(".tab-content");

  // 🟦 Tab Switching Logic
  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      tabs.forEach(t => t.classList.remove("active"));
      tabContents.forEach(tc => tc.classList.remove("active"));

      tab.classList.add("active");
      document.getElementById(tab.dataset.tab).classList.add("active");
    });
  });

  showNotifications();

  // 🟨 Fetch and Render Notifications
  async function showNotifications() {
    try {
      const response = await api.get("/student_profile/profile/notifications");
      if (response.status === "success") {
        const notifications = response.data;

        if (!notifications || notifications.length === 0) {
          renderEmpty();
          return;
        }

        notifications.forEach(n => {
          const div = document.createElement("div");
          div.classList.add("notification-card");

          div.innerHTML = `
            <h3 class="notification-title" data-type="${n.related_type}" data-id="${n.post_id || ''}">
              ${n.title}
            </h3>
            <p class="notification-body">${n.body}</p>
            <small class="ntfTime">${n.created_at}</small><br/>
            <button class="ntfBtn" data-id="${n.id}">Remove</button>
          `;

          const container = document.getElementById(`${n.related_type}-space`);
          if (container) container.appendChild(div);
        });
      }
    } catch (error) {
      console.error("Error fetching notifications", error);
    }
  }

  // 🟥 Remove Notification
  document.addEventListener("click", async (e) => {
    if (e.target.classList.contains("ntfBtn")) {
      const id = e.target.dataset.id;
      try {
        const res = await api.post(`/student_profile/profile/notifications/remove/${id}`);
        if (res.status === "success") {
          e.target.parentElement.remove();
        }
      } catch (err) {
        console.error("Error removing notification", err);
      }
    }

    // 🟩 Redirect Only If Notification is a Post
    if (e.target.classList.contains("notification-title")) {
      if (e.target.dataset.type === "post") {
        const postId = e.target.dataset.id;
        if (postId) window.location.href = `/student/posts/${postId}`;
      }
    }
  });

  // 🟦 Empty State Renderer
  function renderEmpty() {
    const spaces = ["posts", "badges", "connections", "mentions"];
    spaces.forEach(id => {
      const el = document.getElementById(`${id}-space`);
      el.textContent = "No notifications at the moment.";
    });
  }
});