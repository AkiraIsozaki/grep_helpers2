import { Component } from "@angular/core";
@Component({
  selector: "app-x",
  template: `
    <li *ngFor="let row of TRACKED">
      {{ row.code }}
    </li>
  `,
})
export class XComponent {
  data = TRACKED;
}
