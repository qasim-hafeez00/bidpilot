function syncBookings() {
  const sheet = SpreadsheetApp.getActive().getSheetByName('Bookings');
  sheet.appendRow([new Date(), booking.name, booking.slot]);
}
