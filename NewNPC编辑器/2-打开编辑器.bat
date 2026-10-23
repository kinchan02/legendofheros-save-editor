@echo off
rem 用默认浏览器打开本目录下的 NewNPC 编辑器（自动匹配 NewNPC*.html，避免中文文件名编码问题）
for %%f in ("%~dp0NewNPC*.html") do start "" "%%~ff"
exit
