Sub ExportReport()
    Worksheets("Summary").Range("A1:H40").Copy
    Workbooks.Add.Sheets(1).Paste
End Sub
