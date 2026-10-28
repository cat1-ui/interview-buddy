# 前端（web）

面试搭子的前端，基于 React 19 + TypeScript + Vite + Tailwind CSS。

## 启动

```bash
npm install
npm run dev
```

默认运行在 http://localhost:5173。开发服务器已配置代理，把 `/api` 开头的请求转发到后端 http://127.0.0.1:8000，因此**需先启动后端**（见根目录 README）。

## 常用命令

| 命令 | 作用 |
|---|---|
| `npm run dev` | 启动开发服务器 |
| `npm run build` | 生产构建（`tsc -b && vite build`） |
| `npm run lint` | 代码检查（oxlint） |
| `npm run preview` | 预览生产构建产物 |
