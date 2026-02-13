# File Uploads and Streaming in FastAPI

Handling file uploads and streaming in FastAPI is essential for building robust APIs that manage media, documents, or large datasets efficiently. FastAPI provides built-in support for asynchronous file uploads and streaming responses, making it suitable for real-time applications like video transcoding, file processing, and progress tracking. This document explores how to use the `UploadFile` class, stream responses in chunks, track upload progress, and discusses best practices for production systems.

---

## File Uploads in FastAPI

FastAPI simplifies file uploads by abstracting the complexity of raw HTTP requests into a Pythonic interface with the `UploadFile` class. This class offers methods to read, save, and inspect uploaded files directly from HTTP requests using `File(...)` from `fastapi`.

### Example: Basic File Upload

```python
from fastapi import FastAPI, File, UploadFile

app = FastAPI()

@app.post("/upload/")
async def upload_file(file: UploadFile = File(...)):
    return {
        "filename": file.filename,
        "content_type": file.content_type,
        "size": file.size,
    }
```

This endpoint accepts a file and returns metadata without reading the full file into memory. It’s suitable for small files and metadata-only operations.

---

### Reading and Writing File Contents

To process the file content, you can read it in chunks or save it to disk. Here is an example of reading the file in chunks and saving it locally:

```python
import os
from fastapi import FastAPI, File, UploadFile

app = FastAPI()

@app.post("/upload/save/")
async def save_upload_file(file: UploadFile = File(...)):
    file_location = f"uploads/{file.filename}"
    os.makedirs("uploads", exist_ok=True)
    
    with open(file_location, "wb") as buffer:
        for chunk in iter(lambda: file.file.read(1024), b""):
            buffer.write(chunk)
    
    return {"filename": file.filename, "location": file_location}
```

This example uses a loop to read the file in 1KB chunks, reducing memory usage and making it suitable for handling large files.

---

### Edge Cases and Error Handling

When handling file uploads, it’s important to validate file types, sizes, and ensure proper error handling.

```python
from fastapi import FastAPI, UploadFile, File, HTTPException

app = FastAPI()

ALLOWED_TYPES = {"image/jpeg", "image/png"}

@app.post("/upload/strict/")
async def validate_upload(file: UploadFile = File(...)):
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file.content_type}"
        )
    if file.size > 10 * 1024 * 1024:  # 10 MB
        raise HTTPException(
            status_code=413,
            detail="File size exceeds limit of 10 MB"
        )
    return {"filename": file.filename, "valid": True}
```

This example validates content type and size to prevent resource-intensive uploads that could lead to denial-of-service or performance issues.

---

## Streaming Responses in FastAPI

FastAPI supports streaming responses using `StreamingResponse`, which is useful when returning large files or dynamically generated content. This avoids loading the entire response into memory, which is crucial for media or report generation endpoints.

### Example: Streaming a File

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import os

app = FastAPI()

@app.get("/download/{filename}")
async def download_file(filename: str):
    file_path = f"uploads/{filename}"
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return StreamingResponse(open(file_path, "rb"), media_type="application/octet-stream")
```

This endpoint streams a file from disk using `open(..., "rb")`. The `StreamingResponse` object takes care of sending the file in chunks.

---

### Streaming Generated Content

You can also stream dynamically generated content, such as a report generated line-by-line, using a generator function.

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import time

app = FastAPI()

def generate_report():
    for i in range(1, 101):
        time.sleep(0.05)  # Simulate processing delay
        yield f"Line {i}\n"

@app.get("/generate_report")
async def generate_report():
    return StreamingResponse(generate_report(), media_type="text/plain")
```

This pattern is useful for generating logs, reports, or other text-based outputs in a memory-efficient way.

---

### Streaming with Status Updates and Progress Tracking

For advanced use cases like upload progress tracking, you can use middleware or background tasks to monitor progress and provide real-time feedback.

#### Example: Progress Tracking with UploadFile

You can manually read the file in chunks and calculate progress as a percentage:

```python
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse

app = FastAPI()

@app.post("/upload/progress")
async def upload_with_progress(file: UploadFile = File(...)):
    total_bytes = file.size
    bytes_read = 0
    progress = 0

    with open(f"uploads/{file.filename}", "wb") as buffer:
        for chunk in iter(lambda: file.file.read(65536), b""):  # 64KB chunks
            bytes_read += len(chunk)
            buffer.write(chunk)
            progress = int((bytes_read / total_bytes) * 100)
            print(f"Upload progress: {progress}%")  # Can be replaced with websockets/event stream

    return JSONResponse(content={"filename": file.filename, "progress": 100})
```

While this example prints progress to the console, you can integrate it with WebSockets for real-time client-side progress updates. See also **Custom Responses (18)** for more on WebSockets in FastAPI.

---

## Best Practices for File Uploads and Streaming

### 1. Use UploadFile for File Uploads
Always use `UploadFile` for file uploads. It provides a safe and consistent API for handling files, including file names, content types, and file streams.

### 2. Stream Large Files
Use `StreamingResponse` for sending large files or dynamically generated content. This avoids unnecessary memory usage in production.

### 3. Validate Uploads
Validate file types, sizes, and content before accepting uploads. This helps prevent malicious uploads and protects server resources.

### 4. Avoid Reading Entire Files into Memory
Use chunked reading or streaming when possible to handle large files without exhausting server memory.

### 5. Track Upload Progress
For large uploads, track progress and provide feedback to the client via logging, WebSockets, or event streams.

### 6. Use Middleware for Upload Tracking
Leverage middleware (see **Middleware (07)**) to track and log upload metadata, monitor upload speeds, or enforce upload rate limits.

---

## Comparisons with Other Frameworks

Compared to Flask or Django, FastAPI offers superior performance and easier integration with asynchronous file handling. Whereas Flask requires third-party libraries like Flask-Uploads or Werkzeug for similar functionality, FastAPI provides native support for `UploadFile` and `StreamingResponse`.

Compared to Django, which handles file uploads using `request.FILES`, FastAPI is more lightweight and suitable for microservices or APIs that prioritize speed and simplicity.

---

## Troubleshooting and Common Pitfalls

### 1. File Not Being Saved
Ensure that the file is being read in binary mode (`"wb"`), and that the directory exists before writing. Use `os.makedirs(..., exist_ok=True)` to avoid permission errors.

### 2. Uploads Taking Too Long
If upload speed is slow, consider using multipart/form-data compression, increasing chunk size, or using a CDN for uploads.

### 3. Streaming Not Working
Make sure the generator or file reader is yielding data correctly. Avoid returning a `StreamingResponse` with a non-iterable object.

### 4. Memory Leaks in Streaming
Always use `StreamingResponse` in a context manager or ensure that all data streams are properly closed after use.

---

## Real-World Use Cases

- **Cloud Storage APIs**: FastAPI can be used to build APIs that accept file uploads and proxy them to S3, Google Cloud, or Azure Blob Storage.
- **Video Processing Services**: Upload a video file, stream it to a processing service, and then stream the transcoded video back to the user.
- **Log Streaming APIs**: Generate logs or reports in real-time and stream them back to clients as they are written.
- **Media Streaming Platforms**: Serve video or audio files in chunks, reducing buffering and improving streaming performance.

---

## Conclusion

FastAPI’s support for file uploads and streaming makes it ideal for building high-performance APIs that handle large media files, process data in real-time, or serve dynamic content. By using `UploadFile` and `StreamingResponse`, developers can build scalable, memory-efficient applications that are both robust and user-friendly. Understanding when and how to use these tools is critical for senior engineers aiming to design production-grade APIs.