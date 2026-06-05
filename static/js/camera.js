const cameraImg = document.querySelector(".camera-stream");

let cameraStatusTimer = null;

function textOrDash(value) {
    return value || "--";
}

function getInitials(name) {
    if (!name || name === "Không xác định" || name === "Đang chờ nhận diện") {
        return "--";
    }

    return name
        .trim()
        .split(/\s+/)
        .slice(-2)
        .map(part => part[0])
        .join("")
        .toUpperCase();
}

function setBadge(element, text, className) {
    element.textContent = text;
    element.className = `badge ${className}`;
}

const AI_STATUS_MAP = {
    "EYES OPEN":   { text: "Mở",     css: "status-success" },
    "EYES CLOSED": { text: "Nhắm",   css: "status-danger"  },
    "NO FACE":     { text: "--",      css: ""               },
    "NORMAL":      { text: "Bình thường", css: "status-success" },
    "MOUTH OPEN":  { text: "Mở",     css: "status-warning" },
    "YAWNING":     { text: "Ngáp",   css: "status-danger"  },
    "HEAD DOWN":   { text: "Cúi",    css: "status-danger"  },
};

const DROWSY_LEVEL_MAP = {
    "NORMAL":          { text: "Thấp",  css: "status-success" },
    "TIRED":           { text: "Trung bình", css: "status-warning" },
    "DROWSY":          { text: "Cao",   css: "status-danger"  },
    "HEAD DOWN ALERT": { text: "Cao",   css: "status-danger"  },
};

function setStatusBox(id, mapped) {
    const box = document.getElementById(id);
    if (!box) return;
    box.querySelector("strong").textContent = mapped.text;
    box.className = "status-box " + mapped.css;
}

let aiLogEntries = [];

function updateAIStatus(ai) {
    if (!ai) return;

    const eye = AI_STATUS_MAP[ai.eye_status] || AI_STATUS_MAP["NO FACE"];
    const mouth = AI_STATUS_MAP[ai.mouth_status] || AI_STATUS_MAP["NORMAL"];
    const head = AI_STATUS_MAP[ai.head_status] || AI_STATUS_MAP["NORMAL"];
    const level = DROWSY_LEVEL_MAP[ai.drowsy_status] || DROWSY_LEVEL_MAP["NORMAL"];

    setStatusBox("aiEyeStatus", eye);
    setStatusBox("aiMouthStatus", mouth);
    setStatusBox("aiHeadStatus", head);
    setStatusBox("aiAlertLevel", level);

    const now = new Date().toLocaleTimeString("vi-VN", { hour12: false });
    let newEntry = null;

    if (ai.eye_status === "EYES CLOSED") {
        newEntry = { title: "Phát hiện nhắm mắt", detail: `${now} - EAR: ${ai.ear ?? "--"}` };
    } else if (ai.mouth_status === "YAWNING") {
        newEntry = { title: "Phát hiện ngáp", detail: `${now} - MAR: ${ai.mar ?? "--"}` };
    } else if (ai.head_status === "HEAD DOWN") {
        newEntry = { title: "Phát hiện cúi đầu", detail: `${now} - Đầu cúi xuống` };
    } else if (ai.drowsy_status === "DROWSY" || ai.drowsy_status === "TIRED") {
        newEntry = { title: "Cảnh báo buồn ngủ", detail: `${now} - ${ai.drowsy_status}` };
    }

    if (newEntry) {
        aiLogEntries.unshift(newEntry);
        if (aiLogEntries.length > 10) aiLogEntries.length = 10;
        renderAILog();
    }
}

function createLogItem(title, detail) {
    const item = document.createElement("div");
    item.className = "log-item";
    const strong = document.createElement("strong");
    strong.textContent = title;
    const time = document.createElement("div");
    time.className = "log-time";
    time.textContent = detail;
    item.appendChild(strong);
    item.appendChild(time);
    return item;
}

function renderAILog() {
    const logList = document.getElementById("aiLogList");
    if (!logList) return;

    logList.replaceChildren();

    if (aiLogEntries.length === 0) {
        logList.appendChild(createLogItem("Chưa có dữ liệu", "Bắt đầu camera để theo dõi"));
        return;
    }

    for (const e of aiLogEntries) {
        logList.appendChild(createLogItem(e.title, e.detail));
    }
}

function updateCameraPanel(data) {
    const driverName = document.getElementById("cameraDriverName");
    const driverAvatar = document.getElementById("cameraDriverAvatar");
    const driverVerify = document.getElementById("cameraDriverVerify");
    const vehiclePlate = document.getElementById("cameraVehiclePlate");
    const shiftInfo = document.getElementById("cameraShiftInfo");
    const driverPhone = document.getElementById("cameraDriverPhone");
    const recognitionBadge = document.getElementById("cameraRecognitionBadge");

    const driverChip = document.getElementById("cameraDriverChip");
    const confidenceChip = document.getElementById("cameraConfidenceChip");
    const vehicleChip = document.getElementById("cameraVehicleChip");
    const statusChip = document.getElementById("cameraStatusChip");

    updateAIStatus(data.ai);

    if (data.status === "RECOGNIZED") {
        driverName.textContent = data.driver_name;
        driverAvatar.textContent = getInitials(data.driver_name);
        driverVerify.textContent = `Đã xác thực khuôn mặt - độ chính xác ${data.confidence}%`;
        vehiclePlate.textContent = textOrDash(data.vehicle_plate);
        shiftInfo.textContent = `${textOrDash(data.shift_name)} | ${textOrDash(data.shift_time)}`;
        driverPhone.textContent = textOrDash(data.phone);
        setBadge(recognitionBadge, "Đã xác thực", "badge-success");

        driverChip.textContent = `Tài xế: ${data.driver_name}`;
        confidenceChip.textContent = `Độ khớp: ${data.confidence}%`;
        vehicleChip.textContent = `Xe: ${textOrDash(data.vehicle_plate)}`;
        statusChip.textContent = "Trạng thái: Đã nhận diện";
        statusChip.classList.remove("danger");
        return;
    }

    if (data.status === "UNKNOWN_DRIVER") {
        driverName.textContent = "Không xác định";
        driverAvatar.textContent = "??";
        driverVerify.textContent = `Không khớp dữ liệu tài xế - độ gần nhất ${data.confidence}%`;
        vehiclePlate.textContent = "--";
        shiftInfo.textContent = "--";
        driverPhone.textContent = "--";
        setBadge(recognitionBadge, "Không xác định", "badge-danger");

        driverChip.textContent = "Tài xế: Không xác định";
        confidenceChip.textContent = `Độ khớp: ${data.confidence}%`;
        vehicleChip.textContent = "Xe: --";
        statusChip.textContent = "Trạng thái: Chưa khớp dữ liệu";
        statusChip.classList.add("danger");
        return;
    }

    driverName.textContent = "Đang chờ nhận diện";
    driverAvatar.textContent = "--";
    driverVerify.textContent = "Camera chưa xác thực tài xế";
    vehiclePlate.textContent = "--";
    shiftInfo.textContent = "--";
    driverPhone.textContent = "--";
    setBadge(recognitionBadge, "Đang chờ", "badge-warning");

    driverChip.textContent = "Tài xế: Đang chờ";
    confidenceChip.textContent = "Độ khớp: --";
    vehicleChip.textContent = "Xe: --";
    statusChip.textContent = "Trạng thái: Đang phân tích";
    statusChip.classList.remove("danger");
}

function refreshCameraStatus() {
    fetch("/camera_status")
        .then(response => response.json())
        .then(updateCameraPanel)
        .catch(error => {
            console.error("Lỗi refreshCameraStatus:", error);
        });
}

function startStatusPolling() {
    refreshCameraStatus();

    if (cameraStatusTimer) {
        clearInterval(cameraStatusTimer);
    }

    cameraStatusTimer = setInterval(refreshCameraStatus, 1000);
}

function stopStatusPolling() {
    if (cameraStatusTimer) {
        clearInterval(cameraStatusTimer);
        cameraStatusTimer = null;
    }
}

function startCamera() {
    fetch("/start_camera", {
        method: "POST",
    })
    .then(async response => {
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.message || "Không thể bắt đầu camera");
        }
        return data;
    })
    .then(data => {
        cameraImg.src = "/video_feed?t=" + new Date().getTime();
        startStatusPolling();
    })
    .catch(error => {
        console.error("Lỗi startCamera:", error);
        alert(error.message || "Không thể bắt đầu camera");
    });
}

function stopCamera() {
    fetch("/stop_camera", {
        method: "POST"
    })
    .then(response => response.json())
    .then(data => {
        cameraImg.src = "";
        stopStatusPolling();
        refreshCameraStatus();
        aiLogEntries = [];
        renderAILog();
        alert("Đã dừng camera");
    })
    .catch(error => {
        console.error("Lỗi stopCamera:", error);
        alert("Không thể dừng camera");
    });
}

function captureImage() {
    fetch("/capture_image", {
        method: "POST"
    })
    .then(response => response.json())
    .then(data => {
        alert(data.message);
    })
    .catch(error => {
        console.error("Lỗi captureImage:", error);
        alert("Không thể chụp ảnh minh chứng");
    });
}
