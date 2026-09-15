# Network File Sharing Application

## 1. Open Project Folder

``` bat
cd "C:\Users\Dell\Desktop\Optimum Workspace\2026\September\15-09-2026\SST10391\Work 1\Network Practicle\file_sharing"
```

## 2. Start Server

``` bat
py -3 -m server.server
```

## 3. Start Client

``` bat
py -3 -m client.interface
```

## 4. Register User

``` text
register Alice
```

``` text
register Bob
```

``` text
register Charlie
```

## 5. Login

``` text
login Alice
```

``` text
login Bob
```

``` text
login Charlie
```

## 6. Show Users and Transfers

``` text
status
```

## 7. Show Help

``` text
help
```

## 8. Show Current Folder

``` text
pwd
```

## 9. List Files and Folders

``` text
list
```

## 10. Create Folder

``` text
mkdir Documents
```

## 11. Create Nested Folders

``` text
mkdirp University/Networks
```

## 12. Change Folder

``` text
cd Documents
```

``` text
cd University/Networks
```

``` text
cd /
```

## 13. Upload File

``` text
upload "C:\path\to\file.txt" "Documents/file.txt"
```

## 14. Download File

``` text
download /Documents/file.txt "C:\path\to\downloads\file.txt"
```

## 15. Search Files

``` text
search report
```

## 16. Protect Resource

``` text
protect /Documents
```

## 17. Access Protected Resource

``` text
access /Documents
```

## 18. View Notifications

``` text
notifications
```

## 19. Delete File

``` text
delete /Documents/file.txt
```

``` text
yes
```

## 20. Run Automated Tests

``` bat
py -3 -m unittest discover -s tests -v
```

## 21. Run Three-User Demonstration

``` bat
py -3 demo.py
```

## 22. Server Help

``` bat
py -3 -m server.server --help
```

## 23. Client Help

``` bat
py -3 -m client.interface --help
```

## 24. Git Status

``` bat
git status
```

## 25. Git History

``` bat
git log --oneline --all -10
```

## 26. Git Add

``` bat
git add .
```

## 27. Git Commit

``` bat
git commit -m "Complete network file sharing application"
```

## 28. Git Remote

``` bat
git remote -v
```

## 29. Git Push

``` bat
git push -u origin main
```
