$fn = 40;
//bottom();
top();
module top(){
difference(){
    translate([0,0,20.5])cube([30,20,8]);
    translate([0,10,20])rotate([0,90,0])cylinder(d=10,h=30);
        translate([5,3,20])cylinder(d=3.2,h=20);
    translate([5,20-3,20])cylinder(d=3.2,h=20);
    
        translate([30-5,3,20])cylinder(d=3.2,h=20);
    translate([30-5,20-3,20])cylinder(d=3.2,h=20);
    
            translate([5,3,27])cylinder(d=5,h=20);
    translate([5,20-3,27])cylinder(d=5,h=20);
    
        translate([30-5,3,27])cylinder(d=5,h=20);
    translate([30-5,20-3,27])cylinder(d=5,h=20);
} 
}
module bottom(){
difference(){
    cube([30,20,19.5]);
    translate([0,10,20])rotate([0,90,0])cylinder(d=10,h=30);
    
    translate([7,10,0])cylinder(d=4,h=30);
    translate([7,10,10])cylinder(d=8,h=30);
    
    translate([30-7,10,0])cylinder(d=4,h=30);
    translate([30-7,10,10])cylinder(d=8,h=30);
    
    translate([5,3,10])cylinder(d=2.6,h=20);
    translate([5,20-3,10])cylinder(d=2.6,h=20);
    
        translate([30-5,3,10])cylinder(d=2.6,h=20);
    translate([30-5,20-3,10])cylinder(d=2.6,h=20);
}}