$fn = 40;


//bottom();
top();
module top(){
difference(){
translate([0,0,20.5])cube([30,20,10]);
translate([15,-0.01,20])rotate([-90,0,0])cylinder(d=19.5,h=30);
    translate([3,3,20])cylinder(d=3.2,h=20);
    translate([3,20-3,20])cylinder(d=3.2,h=20);
    translate([30-3,3,20])cylinder(d=3.2,h=20);
    translate([30-3,20-3,20])cylinder(d=3.2,h=20);

    translate([3,3,27])cylinder(d=5,h=20);
    translate([3,20-3,27])cylinder(d=5,h=20);
    translate([30-3,3,27])cylinder(d=5,h=20);
    translate([30-3,20-3,27])cylinder(d=5,h=20);
}}
module bottom(){difference(){
    cube([30,20,19.5]);
    translate([15,-0.01,20])rotate([-90,0,0])cylinder(d=19.5,h=30);
    
    translate([15,5,0])cylinder(d=4,h=30);
    translate([15,5,6])cylinder(d=8,h=30);
    
    translate([15,15,0])cylinder(d=4,h=30);
    translate([15,15,6])cylinder(d=8,h=30);
    
    translate([3,3,10])cylinder(d=2.6,h=20);
    translate([3,20-3,10])cylinder(d=2.6,h=20);
    
        translate([30-3,3,10])cylinder(d=2.6,h=20);
    translate([30-3,20-3,10])cylinder(d=2.6,h=20);
}}