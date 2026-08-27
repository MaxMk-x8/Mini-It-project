const http = require('http');
const fs = require('fs');
const path = require('path');

const PORT = process.env.PORT || 3000;

const MIME_TYPES = {
    '.html': 'text/html',
    '.css': 'text/css',
    '.js': 'text/javascript',
    '.json': 'application/json',
    '.png': 'image/png',
    '.jpg': 'image/jpg',
    '.gif': 'image/gif',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon'
};

const server = http.createServer((req, res) => {
    console.log(`${req.method} ${req.url}`);

    // Resolve file path
    let filePath = path.join(__dirname, req.url === '/' ? 'index.html' : req.url);
    
    // Prevent directory traversal attacks
    if (!filePath.startsWith(__dirname)) {
        res.statusCode = 403;
        res.end('Access Denied');
        return;
    }

    const extname = path.extname(filePath);
    let contentType = MIME_TYPES[extname] || 'application/octet-stream';

    fs.readFile(filePath, (error, content) => {
        if (error) {
            if (error.code === 'ENOENT') {
                // If it's a directory, check for index.html inside it
                fs.stat(filePath, (statErr, stats) => {
                    if (!statErr && stats.isDirectory()) {
                        filePath = path.join(filePath, 'index.html');
                        fs.readFile(filePath, (indexErr, indexContent) => {
                            if (indexErr) {
                                serve404(res);
                            } else {
                                res.writeHead(200, { 'Content-Type': 'text/html' });
                                res.end(indexContent, 'utf-8');
                            }
                        });
                    } else {
                        serve404(res);
                    }
                });
            } else {
                res.writeHead(500);
                res.end(`Server Error: ${error.code}`);
            }
        } else {
            res.writeHead(200, { 'Content-Type': contentType });
            res.end(content, 'utf-8');
        }
    });
});

function serve404(res) {
    res.writeHead(404, { 'Content-Type': 'text/html' });
    res.end('<h1>404 Not Found</h1><p>The requested file was not found on this server.</p>', 'utf-8');
}

let currentPort = PORT;
function startServer() {
    server.listen(currentPort, () => {
        console.log(`Server is running at: http://localhost:${currentPort}/`);
    });
}

server.on('error', (err) => {
    if (err.code === 'EADDRINUSE') {
        console.log(`Port ${currentPort} is in use, trying next port...`);
        currentPort++;
        startServer();
    } else {
        console.error('Server error:', err);
    }
});

startServer();

