const cameraImg = document.querySelector(".camera-stream");

function startCamera() {
    fetch("/start_camera", {
        method: "POST"
    })
    .then(response => response.json())
    .then(data => {
        cameraImg.src = "/video_feed?t=" + new Date().getTime();
        alert("Đã bắt đầu camera");
    })
    .catch(error => {
        console.error("Lỗi startCamera:", error);
        alert("Không thể bắt đầu camera");
    });
}

function stopCamera() {
    fetch("/stop_camera", {
        method: "POST"
    })
    .then(response => response.json())
    .then(data => {
        cameraImg.src = "";
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