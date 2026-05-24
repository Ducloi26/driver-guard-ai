const cameraImg = document.querySelector(".camera-stream");

function startCamera() {
    const driverSelect = document.getElementById("driverSelect");
    const driverId = driverSelect ? driverSelect.value : "";

    if (!driverId) {
        alert("Vui lòng chọn tài xế trước khi bật camera");
        return;
    }

    fetch("/start_camera", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ driver_id: driverId })
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
        driverSelect.disabled = true;
        alert("Đã bắt đầu camera");
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
        const driverSelect = document.getElementById("driverSelect");
        if (driverSelect) driverSelect.disabled = false;
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
